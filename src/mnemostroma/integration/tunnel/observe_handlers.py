# tunnel/observe_handlers.py
# HTTP handlers для /tunnel/status|start|stop.
# Импортируется в make_observe_app() обоих адаптеров.
# Единственная копия — без дублирования между http_adapter и sse_adapter.

import asyncio
import logging
import subprocess
import sys

from starlette.requests import Request
from starlette.responses import JSONResponse

from mnemostroma.integration.tunnel.state import get_tunnel_token, get_tunnel_url
from mnemostroma.integration.tunnel.ui_meta import get_meta

logger = logging.getLogger("mnemostroma.tunnel.observe")


async def handle_tunnel_status(request: Request) -> JSONResponse:
    """
    GET /tunnel/status
    Возвращает список чатов с полными per-chat URL.
    Читает только ФС — нет subprocess, нет сетевых вызовов.
    Latency: <5ms.

    Response schema:
        {
            "running": bool,
            "url":     str | null,
            "chats": [
                {
                    "client":      str,
                    "label":       str,
                    "icon":        str,
                    "full_url":    str,
                    "token":       str | null,
                    "hint":        str,
                    "needs_token": bool,
                }
            ]
        }
    """
    url   = get_tunnel_url()
    token = get_tunnel_token()

    if not url:
        return JSONResponse({"running": False, "url": None, "chats": []})

    chats: list[dict] = []
    try:
        from mnemostroma.integration.mcp_oauth_adapter import load_route_config
        routes = load_route_config().routes
    except Exception as e:
        logger.error("handle_tunnel_status: routes.json unavailable: %s", e)
        return JSONResponse(
            {"running": True, "url": url, "chats": [], "error": "routes_unavailable"},
        )

    for path, route_cfg in routes.items():
        client = route_cfg.get("client", "")
        if not client:
            continue

        meta      = get_meta(client)
        auth_list = route_cfg.get("auth", [])
        needs_tok = meta["needs_token"] and ("bearer" in auth_list)

        if needs_tok and token is None:
            logger.warning("route %s: needs_token=True but tunnel_token file missing", path)

        chats.append({
            "client":      client,
            "label":       meta["label"],
            "icon":        meta["icon"],
            "full_url":    f"{url}{path}",
            "token":       token if needs_tok else None,
            "hint":        meta["hint"],
            "needs_token": needs_tok,
        })

    return JSONResponse({"running": True, "url": url, "chats": chats})


def _detach_kwargs() -> dict:
    """Возвращает kwargs для отвязки дочернего процесса от родителя.
    start_new_session — POSIX only; на Windows используем creationflags.
    """
    if sys.platform == "win32":
        return {
            "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS,
        }
    return {"start_new_session": True}


async def handle_tunnel_start(request: Request) -> JSONResponse:
    """
    POST /tunnel/start
    Запускает tunnel в фоне. Возвращает немедленно {started: true}.
    Extension после этого переходит в "starting" state и polling /tunnel/status.
    asyncio.create_subprocess_exec не блокирует event loop (в отличие от subprocess.Popen).
    """
    from mnemostroma.integration.tunnel.resolve import resolve_mnemostroma_executable
    try:
        cmd = resolve_mnemostroma_executable() + ["tunnel", "start"]
        await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **_detach_kwargs(),
        )
    except FileNotFoundError as e:
        logger.error("handle_tunnel_start: executable not found: %s", e)
        return JSONResponse({"started": False, "error": "mnemostroma_not_found"}, status_code=500)
    return JSONResponse({"started": True})


async def handle_tunnel_stop(request: Request) -> JSONResponse:
    """POST /tunnel/stop"""
    from mnemostroma.integration.tunnel.resolve import resolve_mnemostroma_executable
    try:
        cmd = resolve_mnemostroma_executable() + ["tunnel", "stop"]
        await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **_detach_kwargs(),
        )
    except FileNotFoundError as e:
        logger.error("handle_tunnel_stop: executable not found: %s", e)
        return JSONResponse({"stopped": False, "error": "mnemostroma_not_found"}, status_code=500)
    return JSONResponse({"stopped": True})
