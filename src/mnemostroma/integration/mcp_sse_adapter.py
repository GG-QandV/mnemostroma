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

def _make_mcp_server() -> Server:
    """Factory: fresh Server() with registered handlers.

    Called inside handle_sse() for each new client.
    Guarantees isolated negotiation state and absence of race conditions.
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
            result = await safe_ipc_call(name, arguments)
            text = json.dumps(
                result if isinstance(result, (dict, list)) else {"result": result},
                default=str,
                ensure_ascii=False,
            )
            return [TextContent(type="text", text=text)]
        except Exception as exc:
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return srv


# SseServerTransport is safe to share: each session is isolated by UUID.
sse = SseServerTransport("/messages/")

# ── Starlette App (MCP SSE) ───────────────────────────────────────────

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


async def handle_sse(scope, receive, send):
    request = Request(scope, receive)
    if not _check_auth(request):
        response = Response("Unauthorized", status_code=401)
        await response(scope, receive, send)
        return

    mcp_instance = _make_mcp_server()

    async with sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
        await mcp_instance.run(
            read_stream, write_stream, mcp_instance.create_initialization_options()
        )

async def handle_messages(scope, receive, send):
    request = Request(scope, receive)
    if not _check_auth(request):
        response = Response("Unauthorized", status_code=401)
        await response(scope, receive, send)
        return

    await sse.handle_post_message(scope, receive, send)

async def handle_health(request):
    try:
        await safe_ipc_call("ctx_active", {})
        return JSONResponse({"status": "ok", "daemon": "connected", "mcpConfirmed": True})
    except Exception as e:
        return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)

# ── Starlette App (Observe Receiver - Localhost only) ─────────────────

async def handle_mcp_config(request):
    from mnemostroma.integration.tunnel.state import get_tunnel_url
    tunnel_url = get_tunnel_url()
    local_url  = f"http://127.0.0.1:8765/sse?token={TOKEN}"
    public_url = f"{tunnel_url}/sse?token={TOKEN}" if tunnel_url else None
    return JSONResponse({"local_url": local_url, "public_url": public_url})


from mnemostroma.integration.tunnel.observe_handlers import (
    handle_tunnel_start,
    handle_tunnel_status,
    handle_tunnel_stop,
)


async def handle_observe(request):
    """Browser extension -> /observe endpoint."""
    # Localhost (extension) or valid token required
    auth = request.headers.get("X-Mnemo-Token")
    if not check_localhost(request) and (not auth or auth != OBSERVE_TOKEN):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        data = await request.json()
        session_id = data.get("session_id")
        text = data.get("text")
        if not session_id or not text:
            logger.warning(f"Observe 400 payload: {data}"); return JSONResponse({"error": "missing session_id or text"}, status_code=400)
        
        await safe_ipc_call("observe", {"session_id": session_id, "text": text})
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Unified Runner ────────────────────────────────────────────────────

def make_mcp_app():
    return Starlette(  # PATCH-2026-05-17
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",
        routes=[
            Route("/sse", endpoint=ASGIAppWrapper(handle_sse)),
            Route("/messages/", endpoint=ASGIAppWrapper(handle_messages), methods=["POST"]),
            Route("/health", endpoint=handle_health),
        ],
        middleware=[
            Middleware(ServeoHeaderMiddleware),
            Middleware(PrivateNetworkAccessMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )

def make_observe_app():
    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",  # PATCH-2026-05-17
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

async def run():
    logging.basicConfig(level=logging.INFO)

    mcp_config = uvicorn.Config(make_mcp_app(),     host="0.0.0.0",   port=8765, log_level="info")
    obs_config = uvicorn.Config(make_observe_app(), host="127.0.0.1", port=8766, log_level="info")

    servers = [uvicorn.Server(mcp_config)]

    logger.info("Mnemostroma SSE Adapter starting...")
    logger.info("  MCP SSE: http://127.0.0.1:8765/sse (Auth required)")
    
    if not is_port_in_use(8766, "127.0.0.1"):
        servers.append(uvicorn.Server(obs_config))
        logger.info("  Observe: http://127.0.0.1:8766/observe (Localhost only)")
    else:
        logger.info("  Observe: Port 8766 already in use (handled by another adapter)")

    await asyncio.gather(*(s.serve() for s in servers))

if __name__ == "__main__":
    asyncio.run(run())
