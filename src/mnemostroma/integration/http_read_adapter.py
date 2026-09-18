# SPDX-License-Identifier: FSL-1.1-MIT
"""
HTTP Read Adapter — lightweight REST endpoint for direct memory retrieval.

Provides POST /memory/<tool> routes that call safe_ipc_call() directly,
bypassing MCP protocol overhead. Intended for CLI/IDE integrations where
the client config specifies base_url + token instead of MCP transport.

Auth: same Bearer token as mcp_http_adapter (reads ~/.mnemostroma/sse_token).
Port: 8762 (configurable via config.http_read.port).

Read-only: no write/observe routes. Agent never writes memory — Observer handles that.
"""
import asyncio
import json
import logging
import os

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .common import (
    TOKEN,
    PrivateNetworkAccessMiddleware,
    safe_ipc_call,
)
from .mcp_http_adapter import is_port_in_use

logger = logging.getLogger("mnemostroma.http_read_adapter")

# ── Allowed read-only tools ───────────────────────────────────────────
_READ_TOOLS: dict[str, str] = {
    "ctx/semantic":    "ctx_semantic",
    "ctx/anchors":     "ctx_anchors",
    "ctx/search":      "ctx_search",
    "ctx/recent":      "ctx_recent",
    "ctx/get":         "ctx_get",
    "ctx/bridge":      "ctx_bridge",
    "ctx/full":        "ctx_full",
    "content/search":  "content_search",
    "content/raw":     "content_raw",
}

# ── Auth ──────────────────────────────────────────────────────────────

def _check_auth(request: Request) -> bool:
    bearer  = request.headers.get("Authorization", "")
    api_key = request.headers.get("api-key", "")
    query   = request.query_params.get("token", "")
    return bearer == f"Bearer {TOKEN}" or api_key == TOKEN or query == TOKEN

# ── Route handlers ────────────────────────────────────────────────────

async def handle_tool(request: Request) -> JSONResponse:
    """Dispatch POST /memory/<tool> to safe_ipc_call."""
    route_key = request.path_params.get("tool", "")
    tool_name = _READ_TOOLS.get(route_key)
    if not tool_name:
        return JSONResponse(
            {"error": f"unknown tool route: {route_key!r}", "available": list(_READ_TOOLS.keys())},
            status_code=404,
        )

    if not _check_auth(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    try:
        body = await request.json()
    except Exception:
        body = {}

    try:
        result = await safe_ipc_call(tool_name, body)
        payload = result if isinstance(result, (dict, list)) else {"result": result}
        return JSONResponse(payload)
    except Exception as exc:
        logger.error("handle_tool %r failed: %s", tool_name, exc, exc_info=True)
        return JSONResponse({"error": str(exc)}, status_code=500)


async def handle_health(request: Request) -> JSONResponse:
    try:
        await safe_ipc_call("ctx_active", {})
        return JSONResponse({"status": "ok", "adapter": "http_read", "daemon": "connected"})
    except Exception as exc:
        return JSONResponse({"status": "error", "daemon": str(exc)}, status_code=503)


async def handle_routes(request: Request) -> JSONResponse:
    """List available tool routes — useful for IDE config autocomplete."""
    return JSONResponse({
        "routes": [f"/memory/{k}" for k in _READ_TOOLS],
        "auth": "Bearer token (same as MCP HTTP adapter)",
    })

# ── App factory ───────────────────────────────────────────────────────

def make_http_read_app() -> Starlette:
    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",
        routes=[
            Route("/memory/{tool:path}", endpoint=handle_tool,   methods=["POST"]),
            Route("/health",             endpoint=handle_health,  methods=["GET"]),
            Route("/routes",             endpoint=handle_routes,  methods=["GET"]),
        ],
        middleware=[
            Middleware(PrivateNetworkAccessMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ],
    )

# ── Runner ────────────────────────────────────────────────────────────

async def run(
    conductor=None,
    port: int = 8762,
    host: str = "127.0.0.1",
) -> None:
    embedded = conductor is not None
    config = uvicorn.Config(
        make_http_read_app(),
        host=host,
        port=port,
        log_level="warning" if embedded else "info",
        timeout_keep_alive=120,
        timeout_graceful_shutdown=10,
    )
    server = uvicorn.Server(config)

    if not embedded:
        import logging as _log
        _log.basicConfig(level=_log.INFO)
        logger.info("Mnemostroma HTTP Read Adapter starting...")
        logger.info("  Read API: http://%s:%s/memory/<tool> (Auth required)", host, port)
        logger.info("  Routes:   http://%s:%s/routes", host, port)
        logger.info("  Health:   http://%s:%s/health", host, port)
    else:
        logger.info("Embedded HTTP Read server starting on %s:%s", host, port)

    await server.serve()


if __name__ == "__main__":
    asyncio.run(run())
