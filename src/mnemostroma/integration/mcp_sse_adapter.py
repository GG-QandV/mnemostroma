# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import json
import logging
import os
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


class ServeoHeaderMiddleware(BaseHTTPMiddleware):  # PATCH-2026-05-17
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["serveo-skip-browser-warning"] = "true"
        return response


from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import TextContent, Tool

logger = logging.getLogger("mnemostroma.sse_adapter")

_MNEMO_DIR = Path.home() / ".mnemostroma"
_SOCKET_PATH = _MNEMO_DIR / "daemon.sock"
_PIPE_NAME = r"\\.\pipe\mnemostroma"
_TOKEN_PATH = _MNEMO_DIR / "sse_token"

from .common import (
    OBSERVE_TOKEN,
    TOKEN,
    PrivateNetworkAccessMiddleware,
    check_localhost,
    safe_ipc_call,
)

# ── Tool list (keep in sync with mcp_stdio_adapter.py) ──────────────
from .mcp_stdio_adapter import _TOOLS  # Reuse tools definition from stdio adapter

# ── MCP Server factory ────────────────────────────────────────────────
# Create a new Server() for each SSE connection.
# SseServerTransport (sse) — safely shared: isolates sessions by UUID.

def _make_mcp_server(conductor=None) -> Server:
    """Factory: fresh Server() per SSE connection.

    conductor — if provided, calls conductor.dispatch() directly (embedded mode).
    conductor=None — fallback to safe_ipc_call (standalone mode).
    """
    srv = Server("mnemostroma")

    @srv.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in _TOOLS
        ]

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if conductor is not None:
                from mnemostroma.ipc_server import _serialize
                raw = await conductor.dispatch(name, arguments)
                result = _serialize(raw)
            else:
                result = await safe_ipc_call(name, arguments)
            text = json.dumps(
                result if isinstance(result, (dict, list)) else {"result": result},
                default=str,
                ensure_ascii=False,
            )
            return [TextContent(type="text", text=text)]
        except Exception as exc:
            logger.error(f"call_tool {name!r} failed: {exc}", exc_info=True)
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return srv


# SseServerTransport is safe to share: each session is isolated by UUID.
sse = SseServerTransport("/messages/")


class ASGIAppWrapper:
    def __init__(self, app):
        self.app = app
    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


def _check_auth(request: Request) -> bool:
    bearer  = request.headers.get("Authorization", "")
    api_key = request.headers.get("api-key", "")
    query   = request.query_params.get("token", "")
    return bearer == f"Bearer {TOKEN}" or api_key == TOKEN or query == TOKEN


# ── Starlette App factories (conductor injected via closure) ──────────

def make_mcp_app(conductor=None):
    async def handle_sse(scope, receive, send):
        request = Request(scope, receive)
        if not _check_auth(request):
            await Response("Unauthorized", status_code=401)(scope, receive, send)
            return
        mcp_instance = _make_mcp_server(conductor=conductor)
        async with sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
            await mcp_instance.run(
                read_stream, write_stream, mcp_instance.create_initialization_options()
            )

    async def handle_messages(scope, receive, send):
        await sse.handle_post_message(scope, receive, send)

    async def handle_health(request):
        try:
            if conductor is not None:
                await conductor.dispatch("ctx_active", {})
            else:
                await safe_ipc_call("ctx_active", {})
            return JSONResponse({"status": "ok", "daemon": "connected", "mcpConfirmed": True})
        except Exception as e:
            return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)

    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",
        routes=[
            Route("/sse",       endpoint=ASGIAppWrapper(handle_sse)),
            Route("/messages/", endpoint=ASGIAppWrapper(handle_messages), methods=["POST"]),
            Route("/health",    endpoint=handle_health),
        ],
        middleware=[
            Middleware(ServeoHeaderMiddleware),
            Middleware(PrivateNetworkAccessMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )


def make_observe_app(conductor=None):
    async def handle_mcp_config(request):
        from mnemostroma.integration.tunnel.state import get_tunnel_url
        tunnel_url = get_tunnel_url()
        local_url  = f"http://127.0.0.1:8765/sse?token={TOKEN}"
        public_url = f"{tunnel_url}/sse?token={TOKEN}" if tunnel_url else None
        return JSONResponse({"local_url": local_url, "public_url": public_url})

    async def handle_observe(request):
        auth = request.headers.get("X-Mnemo-Token")
        if not check_localhost(request) and (not auth or auth != OBSERVE_TOKEN):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            data = await request.json()
            session_id = data.get("session_id")
            text = data.get("text")
            if not session_id or not text:
                logger.warning(f"Observe 400 payload: {data}")
                return JSONResponse({"error": "missing session_id or text"}, status_code=400)
            if conductor is not None:
                await conductor.dispatch("observe", {"session_id": session_id, "text": text})
            else:
                await safe_ipc_call("observe", {"session_id": session_id, "text": text})
            return JSONResponse({"ok": True})
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)

    from mnemostroma.integration.tunnel.observe_handlers import (
        handle_tunnel_start,
        handle_tunnel_status,
        handle_tunnel_stop,
    )

    async def handle_health(request):
        try:
            if conductor is not None:
                await conductor.dispatch("ctx_active", {})
            else:
                await safe_ipc_call("ctx_active", {})
            return JSONResponse({"status": "ok", "daemon": "connected", "mcpConfirmed": True})
        except Exception as e:
            return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)

    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",
        routes=[
            Route("/health",        endpoint=handle_health),
            Route("/mcp-config",    endpoint=handle_mcp_config),
            Route("/observe",       endpoint=handle_observe,       methods=["POST"]),
            Route("/tunnel/status", endpoint=handle_tunnel_status, methods=["GET"]),
            Route("/tunnel/start",  endpoint=handle_tunnel_start,  methods=["POST"]),
            Route("/tunnel/stop",   endpoint=handle_tunnel_stop,   methods=["POST"]),
        ],
        middleware=[
            Middleware(PrivateNetworkAccessMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )


import socket


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) == 0


async def run(
    conductor=None,
    port: int = 8765,
    port_ext: int | None = 8766,
    host: str = "127.0.0.1",
) -> None:
    embedded = conductor is not None
    # standalone mode keeps 0.0.0.0 for backward compat with external tunnels
    mcp_host = host if embedded else "0.0.0.0"
    signal_handlers = not embedded  # daemon owns signal handlers in embedded mode

    mcp_config = uvicorn.Config(
        make_mcp_app(conductor=conductor),
        host=mcp_host,
        port=port,
        log_level="warning" if embedded else "info",
    )
    obs_config = uvicorn.Config(
        make_observe_app(conductor=conductor),
        host="127.0.0.1",
        port=port_ext or 8766,
        log_level="warning" if embedded else "info",
    )

    servers = [uvicorn.Server(mcp_config)]

    if not embedded:
        logging.basicConfig(level=logging.INFO)
        logger.info("Mnemostroma SSE Adapter starting...")
        logger.info(f"  MCP SSE: http://127.0.0.1:{port}/sse (Auth required)")

    if port_ext and not is_port_in_use(port_ext, "127.0.0.1"):
        servers.append(uvicorn.Server(obs_config))
        if not embedded:
            logger.info(f"  Observe: http://127.0.0.1:{port_ext}/observe (Localhost only)")
    elif not embedded:
        logger.info(f"  Observe: Port {port_ext} already in use (handled by another adapter)")

    await asyncio.gather(*(s.serve() for s in servers))


if __name__ == "__main__":
    asyncio.run(run())
