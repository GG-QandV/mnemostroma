# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import json
import logging
import os
import secrets
import sys
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, Mount
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
import uvicorn

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent

logger = logging.getLogger("mnemostroma.sse_adapter")

_MNEMO_DIR = Path.home() / ".mnemostroma"
_SOCKET_PATH = _MNEMO_DIR / "daemon.sock"
_PIPE_NAME = r"\\.\pipe\mnemostroma"
_TOKEN_PATH = _MNEMO_DIR / "sse_token"

# ── Auth & Token ───────────────────────────────────────────────────────

def _get_or_create_token() -> str:
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    if not _TOKEN_PATH.exists():
        token = secrets.token_urlsafe(32)
        _TOKEN_PATH.write_text(token, encoding="utf-8")
        logger.info(f"Generated new SSE token in {_TOKEN_PATH}")
        return token
    return _TOKEN_PATH.read_text(encoding="utf-8").strip()


TOKEN = _get_or_create_token()

# ── Tool list (keep in sync with mcp_stdio_adapter.py) ──────────────

from .mcp_stdio_adapter import _TOOLS  # Reuse tools definition from stdio adapter

# ── IPC client ────────────────────────────────────────────────────────

_msg_id = 0

def _next_id() -> int:
    global _msg_id
    _msg_id += 1
    return _msg_id

# ── Windows Named Pipe helper ─────────────────────────────────────────

if sys.platform == "win32":
    async def _open_pipe() -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        """Открыть Named Pipe через ProactorEventLoop (Windows-only).

        ProactorEventLoop — дефолт на Windows начиная с Python 3.8.
        create_pipe_connection() — низкоуровневый API, аналог open_unix_connection.
        """
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)

        transport, _ = await loop.create_pipe_connection(
            lambda: protocol,
            _PIPE_NAME,
        )
        writer = asyncio.StreamWriter(transport, protocol, reader, loop)
        return reader, writer


async def _ipc_call(tool: str, args: dict) -> Any:
    """Send one request to the daemon IPC socket, return result or raise."""
    if sys.platform == "win32":
        try:
            reader, writer = await _open_pipe()
        except OSError as e:
            raise ConnectionError(
                f"Mnemostroma daemon not running (pipe unavailable): {e}\n"
                "Start with: mnemostroma start"
            ) from e
    else:
        if not _SOCKET_PATH.exists():
            raise ConnectionError("Mnemostroma daemon not running.")
        reader, writer = await asyncio.open_unix_connection(str(_SOCKET_PATH))

    try:
        msg_id = _next_id()
        payload = json.dumps({"id": msg_id, "tool": tool, "args": args}, ensure_ascii=False)
        writer.write((payload + "\n").encode())
        await writer.drain()

        line = await reader.readline()
        response = json.loads(line.decode())

        if "error" in response:
            raise RuntimeError(response["error"])
        return response.get("result")
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass

# ── MCP Server factory ────────────────────────────────────────────────
# Создаём новый Server() на каждое SSE-соединение.
# SseServerTransport (sse) — шарится безопасно: изолирует сессии по UUID.

def _make_mcp_server() -> Server:
    """Фабрика: свежий Server() с зарегистрированными handlers.

    Вызывается внутри handle_sse() для каждого нового клиента.
    Гарантирует изолированный negotiation state и отсутствие race conditions.
    """
    srv = Server("mnemostroma")

    @srv.list_tools()
    async def list_tools() -> list[Tool]:
        return _TOOLS

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            result = await _ipc_call(name, arguments)
            text = json.dumps(
                result if isinstance(result, (dict, list)) else {"result": result},
                default=str,
                ensure_ascii=False,
            )
            return [TextContent(type="text", text=text)]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return srv


# SseServerTransport безопасно шарить: каждая сессия изолирована по UUID.
sse = SseServerTransport("/messages/")

# ── Starlette App (MCP SSE) ───────────────────────────────────────────

async def handle_sse(request):
    # Auth BEFORE opening SSE stream
    auth = request.headers.get("Authorization")
    if not auth or auth != f"Bearer {TOKEN}":
        return Response("Unauthorized", status_code=401)

    # Новый изолированный Server() для этого соединения
    mcp_instance = _make_mcp_server()

    async with sse.connect_sse(request.scope, request.receive, request._send) as (read_stream, write_stream):
        await mcp_instance.run(
            read_stream, write_stream, mcp_instance.create_initialization_options()
        )

async def handle_messages(request):
    # Auth check
    auth = request.headers.get("Authorization")
    if not auth or auth != f"Bearer {TOKEN}":
        return Response("Unauthorized", status_code=401)

    return await sse.handle_post_message(request.scope, request.receive, request._send)

async def handle_health(request):
    try:
        await _ipc_call("ctx_active", {})
        return JSONResponse({"status": "ok", "daemon": "connected"})
    except Exception as e:
        return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)

# ── Starlette App (Observe Receiver - Localhost only) ─────────────────

async def handle_observe(request):
    """Browser extension -> /observe endpoint."""
    try:
        data = await request.json()
        session_id = data.get("session_id")
        text = data.get("text")
        if not session_id or not text:
            return JSONResponse({"error": "missing session_id or text"}, status_code=400)
        
        await _ipc_call("observe", {"session_id": session_id, "text": text})
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Unified Runner ────────────────────────────────────────────────────

def make_mcp_app():
    return Starlette(
        debug=True,
        routes=[
            Route("/sse", endpoint=handle_sse),
            Route("/messages/", endpoint=handle_messages, methods=["POST"]),
            Route("/health", endpoint=handle_health),
        ]
    )

def make_observe_app():
    return Starlette(
        debug=True,
        routes=[
            Route("/observe", endpoint=handle_observe, methods=["POST"]),
        ],
        middleware=[
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )

async def run():
    logging.basicConfig(level=logging.INFO)
    
    # Run two uvicorn servers in parallel
    mcp_config = uvicorn.Config(make_mcp_app(), host="0.0.0.0", port=8765, log_level="info")
    obs_config = uvicorn.Config(make_observe_app(), host="127.0.0.1", port=8766, log_level="info")
    
    mcp_server = uvicorn.Server(mcp_config)
    obs_server = uvicorn.Server(obs_config)
    
    logger.info(f"Mnemostroma SSE Adapter starting...")
    logger.info(f"  MCP SSE: http://localhost:8765/sse (Auth required)")
    logger.info(f"  Observe: http://localhost:8766/observe (Localhost only)")
    
    await asyncio.gather(
        mcp_server.serve(),
        obs_server.serve()
    )

if __name__ == "__main__":
    asyncio.run(run())
