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
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, Mount
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
import uvicorn

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent

logger = logging.getLogger("mnemostroma.http_adapter")

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
        logger.info(f"Generated new SSE/HTTP token in {_TOKEN_PATH}")
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
        """Open Named Pipe via ProactorEventLoop (Windows-only)."""
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

def _make_mcp_server() -> Server:
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

# ── Session Manager (replaces SseServerTransport) ─────────────────────

session_manager = StreamableHTTPSessionManager(
    app=_make_mcp_server(),
    event_store=None,       # stateless — no session persistence needed
    json_response=True,     # return JSON, not binary stream
    stateless=True,         # crucial for cloudflared quick tunnel
)

# ── Starlette App (MCP HTTP) ───────────────────────────────────────────

async def handle_mcp(request: Request):
    auth = request.headers.get("Authorization")
    if not auth or auth != f"Bearer {TOKEN}":
        return Response("Unauthorized", status_code=401)
    
    async with session_manager.run():
        await session_manager.handle_request(request.scope, request.receive, request._send)
    # The session_manager handles the response, so we don't need to return anything explicitly, 
    # but to satisfy starlette if it expects something, wait handle_request usually consumes it all.
    return Response(status_code=200) if not request._send else None # A dummy fallback just in case, but handle_request handles it.

async def handle_health(request: Request):
    try:
        await _ipc_call("ctx_active", {})
        return JSONResponse({"status": "ok", "daemon": "connected", "mcpConfirmed": True})
    except Exception as e:
        return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)

# ── Starlette App (Observe Receiver - Localhost only) ─────────────────

async def handle_observe(request: Request):
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

async def handle_mcp_config(request: Request) -> JSONResponse:
    """Return ready-to-use MCP client config, with Serveo headers if tunnel is active."""
    serveo_path = _MNEMO_DIR / "serveo_url"
    if serveo_path.exists():
        public_url = serveo_path.read_text().strip()
        endpoint = f"{public_url}/mcp"
        headers = {"serveo-skip-browser-warning": "true"}
    else:
        endpoint = "http://localhost:8768/mcp"
        headers = {}
    return JSONResponse({
        "mcpServers": {
            "mnemostroma": {
                "url": endpoint,
                "headers": headers,
            }
        }
    })

def make_mcp_app():
    return Starlette(
        debug=True,
        routes=[
            Route("/mcp",        endpoint=handle_mcp,        methods=["GET", "POST", "DELETE"]),
            Route("/health",     endpoint=handle_health),
            Route("/mcp-config", endpoint=handle_mcp_config, methods=["GET"]),
        ]
    )

def make_observe_app():
    return Starlette(
        debug=True,
        routes=[
            Route("/health",  endpoint=handle_health),
            Route("/observe", endpoint=handle_observe, methods=["POST"]),
        ],
        middleware=[
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )

import socket

def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0

async def run():
    logging.basicConfig(level=logging.INFO)

    mcp_config = uvicorn.Config(make_mcp_app(),     host="0.0.0.0",   port=8768, log_level="info")
    obs_config = uvicorn.Config(make_observe_app(), host="127.0.0.1", port=8766, log_level="info")

    servers = [uvicorn.Server(mcp_config)]

    logger.info("Mnemostroma HTTP Adapter starting...")
    logger.info("  MCP HTTP: http://localhost:8768/mcp (Auth required)")
    
    if not is_port_in_use(8766, "127.0.0.1"):
        servers.append(uvicorn.Server(obs_config))
        logger.info("  Observe: http://127.0.0.1:8766/observe (Localhost only)")
    else:
        logger.info("  Observe: Port 8766 already in use (handled by another adapter)")

    await asyncio.gather(*(s.serve() for s in servers))

if __name__ == "__main__":
    asyncio.run(run())
