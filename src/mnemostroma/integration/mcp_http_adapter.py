# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import json
import logging
import os
from pathlib import Path

import uvicorn
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import TextContent, Tool
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

logger = logging.getLogger("mnemostroma.http_adapter")

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

def _make_mcp_server(conductor=None) -> Server:
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

# ── Session Manager (через app.state, не global) ──────────────────────

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


async def handle_mcp(scope, receive, send):
    request = Request(scope, receive)
    if not _check_auth(request):
        response = Response("Unauthorized", status_code=401)
        await response(scope, receive, send)
        return
    
    # Accept-patch для Perplexity (HTTP 406 workaround)
    headers = list(scope.get("headers", []))
    has_accept = False
    for i, (k, v) in enumerate(headers):
        if k.lower() == b"accept":
            has_accept = True
            if b"application/json" not in v:
                headers[i] = (b"accept", b"application/json")
            break
    if not has_accept:
        headers.append((b"accept", b"application/json"))
    scope["headers"] = headers

    sm = scope["app"].state.sm
    await sm.handle_request(scope, receive, send)

async def handle_health(request: Request):
    try:
        await safe_ipc_call("ctx_active", {})
        return JSONResponse({"status": "ok", "daemon": "connected", "mcpConfirmed": True})
    except Exception as e:
        return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)

# ── Starlette App (Observe Receiver - Localhost only) ─────────────────

from mnemostroma.integration.tunnel.observe_handlers import (
    handle_tunnel_start,
    handle_tunnel_status,
    handle_tunnel_stop,
)


async def handle_observe(request: Request):  # PATCH-2026-05-17
    # Localhost (extension) or valid token required
    auth = request.headers.get("X-Mnemo-Token")
    if not check_localhost(request) and (not auth or auth != OBSERVE_TOKEN):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    try:
        data = await request.json()
        session_id = data.get("session_id")
        text = data.get("text")
        if not session_id or not text:
            return JSONResponse({"error": "missing session_id or text"}, status_code=400)
        
        await safe_ipc_call("observe", {"session_id": session_id, "text": text})
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

# ── Unified Runner ────────────────────────────────────────────────────

async def handle_mcp_config(request: Request) -> JSONResponse:
    """Return ready-to-use MCP client config."""
    from mnemostroma.integration.tunnel.state import get_tunnel_url
    public_url = get_tunnel_url()
    if public_url:
        endpoint = f"{public_url}/mcp"
        headers = {"serveo-skip-browser-warning": "true"}
    else:
        endpoint = "http://127.0.0.1:8768/mcp"
        headers = {}
    return JSONResponse({
        "mcpServers": {
            "mnemostroma": {
                "url": endpoint,
                "headers": headers,
            }
        }
    })

from contextlib import asynccontextmanager


def make_mcp_app(conductor=None):
    @asynccontextmanager
    async def lifespan(app):
        sm = StreamableHTTPSessionManager(
            app=_make_mcp_server(conductor=conductor),
            event_store=None,
            json_response=True,
            stateless=True,
        )
        async with sm.run():
            app.state.sm = sm
            yield

    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",
        lifespan=lifespan,
        routes=[
            Route("/mcp",        endpoint=ASGIAppWrapper(handle_mcp),        methods=["GET", "POST", "DELETE"]),
            Route("/health",     endpoint=handle_health),
            Route("/mcp-config", endpoint=handle_mcp_config, methods=["GET"]),
        ],
        middleware=[
            Middleware(PrivateNetworkAccessMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )

def make_observe_app():
    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",  # PATCH-2026-05-17
        routes=[
            Route("/health",        endpoint=handle_health),
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
    port: int = 8768,
    host: str = "127.0.0.1",
) -> None:
    embedded = conductor is not None
    mcp_host = host if embedded else "0.0.0.0"

    mcp_config = uvicorn.Config(
        make_mcp_app(conductor=conductor),
        host=mcp_host,
        port=port,
        log_level="warning" if embedded else "info",
    )
    servers = [uvicorn.Server(mcp_config)]

    if not embedded:
        logging.basicConfig(level=logging.INFO)
        logger.info("Mnemostroma HTTP Adapter starting...")
        logger.info("  MCP HTTP: http://127.0.0.1:%s/mcp (Auth required)", port)
        obs_config = uvicorn.Config(
            make_observe_app(), host="127.0.0.1", port=8766, log_level="info"
        )
        if not is_port_in_use(8766, "127.0.0.1"):
            servers.append(uvicorn.Server(obs_config))
            logger.info("  Observe: http://127.0.0.1:8766/observe (Localhost only)")
        else:
            logger.info("  Observe: Port 8766 already in use (handled by another adapter)")
    else:
        logger.info("Embedded MCP HTTP server starting on %s:%s", mcp_host, port)

    await asyncio.gather(*(s.serve() for s in servers))

if __name__ == "__main__":
    asyncio.run(run())
