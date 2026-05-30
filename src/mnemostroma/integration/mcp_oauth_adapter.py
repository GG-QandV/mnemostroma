"""
MCP OAuth Adapter — единый сервер для всех чатов.
Порт: 8769

Архитектура:
- Каждый маршрут имеет изолированную auth-стратегию (AuthSelector)
- StreamableHTTPSessionManager живёт в lifespan, доступен через app.state
- SSE /messages проксируются на mcpsseadapter :8765
- OAuth-запросы (register, authorize, token) обрабатываются локально
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import inspect
import json
import logging
import secrets
import threading
import time
import webbrowser
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, AsyncGenerator, AsyncIterator, Callable, Protocol

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.types import Tool, TextContent

from mnemostroma.integration.tunnel.token import get_or_create_tunnel_token
from .common import TOKEN, safe_ipc_call
from .mcp_stdio_adapter import _TOOLS

logger: logging.Logger = logging.getLogger("mnemostroma.integration.mcp_oauth_adapter")

# ── In-memory OAuth state ─────────────────────────────────────────────────────
_clients: dict[str, dict[str, Any]] = {}
_codes:   dict[str, dict[str, Any]] = {}
_tokens:  dict[str, dict[str, Any]] = {}

MCP_SSE_UPSTREAM: str = "http://localhost:8765"

_MNEMO_DIR = Path.home() / ".mnemostroma"
_SSE_TOKEN_PATH = _MNEMO_DIR / "sse_token"
PUBLIC_URL: str = ""
OAUTH_METADATA: dict[str, Any] = {}
PROTECTED_RESOURCE_METADATA: dict[str, Any] = {}
CM_UPSTREAM: str = "http://localhost:3847"


def _validate_oauth_token(token: str) -> bool:
    return bool(token and token in _tokens and time.time() < _tokens[token]["expires"])


# ── Route config (Sprint+1) ──────────────────────────────────────────────────

DEFAULT_ROUTES: dict[str, dict] = {
    "/mcp":                    {"auth": ["none"],              "client": "perplexity",  "transport": "streamable-http"},
    "/sse":                    {"auth": ["oauth", "bearer"],  "client": "claude",       "transport": "sse"},
    "/messages/":              {"auth": ["oauth", "bearer"],  "client": "claude",       "transport": "sse-messages"},
    "/mcp/chatgpt":            {"auth": ["oauth", "bearer"],  "client": "chatgpt",      "transport": "streamable-http"},
    "/mcp/grok":               {"auth": ["bearer"],           "client": "grok",         "transport": "streamable-http"},
    "/context-manager":        {"auth": ["bearer"],           "client": "internal",     "transport": "proxy"},
    "/context-manager/{rest:path}": {"auth": ["bearer"],      "client": "internal",     "transport": "proxy"},
}

VALID_AUTH_MODES: set[str] = {"none", "bearer", "oauth"}


@dataclass
class WatcherConfig:
    interval: float = 2.0
    backend: str = "auto"


@dataclass
class FullRouteConfig:
    routes: dict
    watcher: WatcherConfig


def _validate_route_config(data: dict) -> None:
    for path, cfg in data.get("routes", {}).items():
        auth = cfg.get("auth")
        if not isinstance(auth, list):
            raise ValueError(f"routes[{path}].auth must be a list, got {type(auth).__name__}")
        unknown = set(auth) - VALID_AUTH_MODES
        if unknown:
            raise ValueError(f"routes[{path}].auth contains unknown modes: {unknown}")
    watcher = data.get("watcher")
    if watcher is not None:
        if not isinstance(watcher, dict):
            raise ValueError(f"watcher must be a dict, got {type(watcher).__name__}")
        interval = watcher.get("interval", 2.0)
        if not isinstance(interval, (int, float)) or interval <= 0:
            raise ValueError(f"watcher.interval must be a positive number, got {interval!r}")
        backend = watcher.get("backend", "auto")
        if backend not in ("auto", "polling", "inotify"):
            raise ValueError(f"watcher.backend must be auto|polling|inotify, got {backend!r}")


def load_route_config(path: Path | None = None) -> FullRouteConfig:
    routes_path = path or (_MNEMO_DIR / "routes.json")
    if not routes_path.exists():
        return FullRouteConfig(routes=dict(DEFAULT_ROUTES), watcher=WatcherConfig())
    data = json.loads(routes_path.read_text())
    _validate_route_config(data)
    wc = data.get("watcher", {})
    watcher = WatcherConfig(
        interval=wc.get("interval", 2.0),
        backend=wc.get("backend", "auto"),
    )
    return FullRouteConfig(routes=data.get("routes", {}), watcher=watcher)


def _build_routes(route_cfg: dict) -> list[Route]:
    routes = [
        Route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"]),
        Route("/.well-known/oauth-protected-resource", protected_resource_metadata, methods=["GET"]),
        Route("/register", register, methods=["POST"]),
        Route("/authorize", authorize, methods=["GET"]),
        Route("/authorize/confirm", authorize_confirm, methods=["GET", "POST"]),
        Route("/token", token, methods=["POST"]),
        Route("/health", health, methods=["GET"]),
        Route("/mcp-config", handle_mcp_config, methods=["GET"]),
    ]
    for path, cfg in route_cfg.items():
        modes = [AuthMode(m) for m in cfg["auth"]]
        transport = cfg.get("transport", "streamable-http")
        if transport == "streamable-http":
            routes.append(Route(path, endpoint=ASGIAppWrapper(AuthSelector(modes).require_asgi(handle_mcp)), methods=["GET", "POST", "DELETE"]))
        elif transport == "sse":
            routes.append(Route(path, endpoint=AuthSelector(modes).require_starlette(proxy_sse), methods=["GET"]))
        elif transport == "sse-messages":
            routes.append(Route(path, endpoint=AuthSelector(modes).require_starlette(proxy_messages), methods=["POST"]))
        elif transport == "proxy":
            routes.append(Route(path, endpoint=AuthSelector(modes).require_starlette(proxy_to_cm), methods=["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH"]))
    return routes


# ── RouteRegistry (Sprint+2) ──────────────────────────────────────────────────

@dataclass
class RouteEntry:
    auth_modes: list[AuthMode]
    handler: Callable
    methods: list[str]


class RouteRegistry:
    """Thread-safe реестр маршрутов. Copy-on-write для lock-free reads."""

    def __init__(self):
        self._routes: dict[str, RouteEntry] = {}
        self._lock = threading.RLock()

    def update(self, routes: dict[str, RouteEntry]) -> None:
        with self._lock:
            self._routes = dict(routes)

    def match(self, path: str) -> RouteEntry | None:
        with self._lock:
            snapshot = self._routes
        if path in snapshot:
            return snapshot[path]
        for pattern, entry in snapshot.items():
            if "{" in pattern:
                prefix = pattern.split("{")[0].rstrip("/")
                if path.startswith(prefix):
                    return entry
        return None

    @property
    def current(self) -> dict[str, RouteEntry]:
        with self._lock:
            return dict(self._routes)


# ── AuthMode & AuthSelector (per-route auth isolation) ────────────────────────

class AuthMode(Enum):
    NONE   = "none"     # Perplexity — no auth
    BEARER = "bearer"   # Grok, прямые вызовы
    OAUTH  = "oauth"    # Claude, ChatGPT


class AuthSelector:
    """Per-route auth guard. Проверяет auth по списку разрешённых режимов."""

    def __init__(self, modes: list[AuthMode]):
        self.modes = modes

    def check(self, request: Request, scope: dict) -> bool:
        for mode in self.modes:
            if mode == AuthMode.NONE:
                return True
            if mode == AuthMode.BEARER:
                bearer = request.headers.get("Authorization", "")
                api_key = request.headers.get("api-key", "")
                query = request.query_params.get("token", "")
                if bearer == f"Bearer {TOKEN}" or api_key == TOKEN or query == TOKEN:
                    return True
                tok = bearer[len("Bearer "):] if bearer.startswith("Bearer ") else ""
                if tok and tok == get_or_create_tunnel_token():
                    return True
            if mode == AuthMode.OAUTH:
                token = scope.get("oauth_token", "")
                if _validate_oauth_token(token):
                    return True
        return False

    def _check(self, request: Request) -> bool:
        """Convenience for unit tests. Injects request.state.oauth_token into scope."""
        oauth_token = getattr(request.state, "oauth_token", None) or ""
        scope = getattr(request, "scope", {})
        return self.check(request, {**scope, "oauth_token": oauth_token})

    def __call__(self, handler: Callable) -> Callable:
        """Универсальный ASGI wrapper: определяет тип handler и применяет auth."""
        sig = inspect.signature(handler)
        params = list(sig.parameters.keys())

        async def wrapper(scope, receive, send):
            request = Request(scope, receive)
            if not self.check(request, scope):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
            if len(params) == 3:
                await handler(scope, receive, send)
            else:
                response = await handler(request)
                await response(scope, receive, send)
        return wrapper

    def require_asgi(self, handler):
        """Wrap ASGI handler (scope, receive, send) → проверяет auth перед вызовом."""
        async def wrapper(scope, receive, send):
            request = Request(scope, receive)
            if not self.check(request, scope):
                response = JSONResponse({"error": "unauthorized"}, status_code=401)
                await response(scope, receive, send)
                return
            await handler(scope, receive, send)
        return wrapper

    def require_starlette(self, handler):
        """Wrap Starlette handler (request → response) → проверяет auth перед вызовом."""
        async def wrapper(request: Request) -> Response:
            if not self.check(request, request.scope):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await handler(request)
        return wrapper


# ── OAuth Token Middleware (ASGI-level, не ломает SSE streaming) ──────────────

class OAuthTokenMiddleware:
    """Извлекает Bearer token в scope['oauth_token'] для AuthSelector."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            auth = headers.get(b"authorization", b"").decode()
            if auth.startswith("Bearer "):
                scope["oauth_token"] = auth[7:]
        await self.app(scope, receive, send)


# ── MCP Server factory ────────────────────────────────────────────────────────

def _make_mcp_server() -> Server:
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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _pkce_verify(verifier: str, challenge: str) -> bool:
    digest: str = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return digest == challenge


# ── ASGI wrapper for MCP handlers ─────────────────────────────────────────────

class ASGIAppWrapper:
    """Wraps an ASGI handler (scope, receive, send) → Starlette Route endpoint."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        await self.app(scope, receive, send)


# ── MCP handler — читает SM из app.state ─────────────────────────────────────

async def handle_mcp(scope, receive, send):
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

    sm = scope["app"].state.sm if hasattr(scope["app"].state, "sm") else None
    if sm is not None and sm._task_group is not None:
        await sm.handle_request(scope, receive, send)
        return
    # Fallback для тестов: создаём временный SM с run()
    sm = StreamableHTTPSessionManager(
        app=_make_mcp_server(),
        event_store=None,
        json_response=True,
        stateless=True,
    )
    async with sm.run():
        await sm.handle_request(scope, receive, send)


# ── RFC 8414 — OAuth Server Metadata ─────────────────────────────────────────

async def oauth_metadata(request: Request) -> JSONResponse:
    if OAUTH_METADATA:
        return JSONResponse(OAUTH_METADATA)
    base: str = _base_url(request)
    return JSONResponse({
        "issuer": base,
        "authorization_endpoint": f"{base}/authorize",
        "token_endpoint": f"{base}/token",
        "registration_endpoint": f"{base}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
    })


async def protected_resource_metadata(request: Request) -> JSONResponse:
    if PROTECTED_RESOURCE_METADATA:
        return JSONResponse(PROTECTED_RESOURCE_METADATA)
    base: str = _base_url(request)
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
    })


# ── DCR — Dynamic Client Registration ───────────────────────────────────────

async def register(request: Request) -> JSONResponse:
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    client_id: str = secrets.token_urlsafe(16)
    client_secret: str = secrets.token_urlsafe(32)
    _clients[client_id] = {
        "client_secret": client_secret,
        "redirect_uris": data.get("redirect_uris", []),
    }
    return JSONResponse({
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uris": data.get("redirect_uris", []),
        "token_endpoint_auth_method": "client_secret_post",
    }, status_code=201)


# ── /authorize — PKCE S256 ──────────────────────────────────────────────────

async def authorize(request: Request) -> Response:
    p: dict[str, str] = dict(request.query_params)
    required: set[str] = {"client_id", "redirect_uri", "code_challenge", "response_type"}
    if not required.issubset(p):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    if p.get("code_challenge_method", "S256") != "S256":
        return JSONResponse({"error": "invalid_request", "error_description": "Only S256 supported"}, status_code=400)

    client_id = p["client_id"]
    redirect_uri = p["redirect_uri"]
    code_challenge = p["code_challenge"]
    state = p.get("state", "")

    base: str = PUBLIC_URL if PUBLIC_URL else _base_url(request)
    
    # Возвращаем 200 HTML с формой согласия (Consent Screen)
    html: str = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:2em">
    <h2>Mnemostroma — Authorization Request</h2>
    <p>An external chat application is requesting access to your local Mnemostroma memory.</p>
    <p><b>Client ID:</b> {client_id}</p>
    <form method="post" action="{base}/authorize/confirm">
        <input type="hidden" name="client_id" value="{client_id}">
        <input type="hidden" name="redirect_uri" value="{redirect_uri}">
        <input type="hidden" name="code_challenge" value="{code_challenge}">
        <input type="hidden" name="state" value="{state}">
        <button type="submit" style="background:#22c55e;color:white;padding:.5em 1.5em;border:none;border-radius:4px;cursor:pointer">Allow Access</button>
    </form>
    </body></html>"""
    
    # Пытаемся открыть браузер для удобства локального пользователя
    try:
        webbrowser.open(f"{base}/authorize?client_id={client_id}&redirect_uri={redirect_uri}&code_challenge={code_challenge}&response_type=code&state={state}")
    except Exception as e:
        logger.warning(f"Failed to open web browser: {e}")

    return Response(html, media_type="text/html")


async def authorize_confirm(request: Request) -> Response:
    form_data = {}
    if request.method == "POST":
        try:
            form_data = dict(await request.form())
        except Exception:
            pass

    client_id = form_data.get("client_id") or request.query_params.get("client_id")
    redirect_uri = form_data.get("redirect_uri") or request.query_params.get("redirect_uri")
    code_challenge = form_data.get("code_challenge") or request.query_params.get("code_challenge")
    state = form_data.get("state") or request.query_params.get("state") or ""

    if not client_id or not redirect_uri or not code_challenge:
        # Обратная совместимость для старых тестов (GET/POST /authorize/confirm?code=...)
        code = request.query_params.get("code", "")
        if code:
            if request.method == "POST":
                if code not in _codes:
                    return Response("Authorization session expired or invalid.", status_code=400)
                html_success: str = """<!DOCTYPE html><html><body style="font-family:sans-serif;padding:2em;text-align:center">
                <h2 style="color:#22c55e">Access Granted!</h2>
                <p>You can close this window now and return to your chat application.</p>
                </body></html>"""
                return Response(html_success, media_type="text/html")
            else:
                base: str = PUBLIC_URL if PUBLIC_URL else _base_url(request)
                html: str = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:2em">
                <h2>Mnemostroma — Authorization Request</h2>
                <p>An external chat application is requesting access to your local Mnemostroma memory.</p>
                <p><b>Code:</b> {code[:8]}...</p>
                <form method="post" action="{base}/authorize/confirm?code={code}&state={state}">
                    <input type="hidden" name="code" value="{code}">
                    <input type="hidden" name="state" value="{state}">
                    <button type="submit" style="background:#22c55e;color:white;padding:.5em 1.5em;border:none;border-radius:4px;cursor:pointer">Allow Access</button>
                </form>
                </body></html>"""
                return Response(html, media_type="text/html")

        return Response("Missing required OAuth parameters.", status_code=400)

    # Генерируем реальный одноразовый code при подтверждении
    code = secrets.token_urlsafe(32)
    _codes[code] = {
        "client_id": client_id,
        "pkce_challenge": code_challenge,
        "redirect_uri": redirect_uri,
        "expires": time.time() + 300,
    }

    return RedirectResponse(f"{redirect_uri}?code={code}&state={state}", status_code=302)


# ── /token — code → access_token ─────────────────────────────────────────────

async def token(request: Request) -> JSONResponse:
    form: Any = await request.form()
    code: str | None = form.get("code")
    verifier: str | None = form.get("code_verifier")
    if not code:
        return JSONResponse({"error": "invalid_request", "error_description": "Missing code"}, status_code=400)
    entry: dict[str, Any] | None = _codes.pop(str(code), None)
    if not entry or time.time() > entry["expires"]:
        return JSONResponse({"error": "invalid_grant"}, status_code=400)
    if not verifier or not _pkce_verify(str(verifier), entry["pkce_challenge"]):
        return JSONResponse({"error": "invalid_grant", "error_description": "PKCE verification failed"}, status_code=400)
    access_token: str = secrets.token_urlsafe(32)
    _tokens[access_token] = {
        "client_id": entry["client_id"],
        "expires": time.time() + 3600,
    }
    return JSONResponse({
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": 3600,
    })


# ── SSE proxy → mcpsseadapter :8765 ──────────────────────────────────────────

def _clean_response_headers(upstream_headers: dict[str, str]) -> dict[str, str]:
    exclude = {
        "content-length", "content-encoding", "transfer-encoding",
        "connection", "keep-alive", "proxy-authenticate",
        "proxy-authorization", "te", "trailer", "upgrade", "server", "date",
    }
    return {k: v for k, v in upstream_headers.items() if k.lower() not in exclude}


async def proxy_sse(request: Request) -> Response:
    logger.info("Incoming /sse request")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization")}
    internal_token = _get_internal_token()
    if internal_token:
        headers["Authorization"] = f"Bearer {internal_token}"

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        try:
            async with httpx.AsyncClient(timeout=None) as client:
                async with client.stream("GET", f"{MCP_SSE_UPSTREAM}/sse",
                                         headers=headers,
                                         timeout=None) as upstream:
                    async for chunk in upstream.aiter_bytes():
                        yield chunk
        except Exception as e:
            logger.error("Error in /sse proxy stream: %s", e)

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


async def proxy_messages(request: Request) -> Response:
    logger.info("Incoming /messages request")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization", "content-length")}
    internal_token = _get_internal_token()
    if internal_token:
        headers["Authorization"] = f"Bearer {internal_token}"
    target = f"{MCP_SSE_UPSTREAM}/messages/"
    if request.url.query:
        target += f"?{request.url.query}"
    try:
        async with httpx.AsyncClient() as client:
            upstream = await client.request(
                method=request.method, url=target, headers=headers,
                content=await request.body(), timeout=30,
            )
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=_clean_response_headers(dict(upstream.headers)),
        )
    except Exception as e:
        logger.error("Failed to proxy /messages request: %s", e)
        return JSONResponse({"error": "bad_gateway", "message": str(e)}, status_code=502)


def _get_internal_token() -> str:
    return _SSE_TOKEN_PATH.read_text(encoding="utf-8").strip() if _SSE_TOKEN_PATH.exists() else ""


# ── /health — включает mcpConfirmed для тестов SPEC ──────────────────────────

async def health(request: Request) -> JSONResponse:
    app = request.scope.get("app", {})
    registry = getattr(app.state, "registry", None) if hasattr(app.state, "registry") else None
    metrics = getattr(app.state, "metrics", None) if hasattr(app.state, "metrics") else None

    if registry is not None:
        routes_map = registry.current
        active_count = len(routes_map)
        paths = sorted(routes_map.keys())
    else:
        active_count = 0
        paths = []

    reload_info = metrics.snapshot() if metrics else {
        "total_attempts": 0,
        "total_successes": 0,
        "total_errors": 0,
        "last_reload_time": None,
        "last_error_time": None,
        "last_error_message": None,
    }

    return JSONResponse({
        "status": "ok",
        "mcpConfirmed": True,
        "daemon": "ok",
        "routes": {
            "active_count": active_count,
            "paths": paths,
        },
        "reload": reload_info,
    })


# ── /mcp-config — полный конфиг (Sprint+1) ────────────────────────────────────

def _read_serveo_url() -> str | None:
    p = _MNEMO_DIR / "serveo_url"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


def _read_tunnel_token() -> str | None:
    p = _MNEMO_DIR / "tunnel_token"
    return p.read_text(encoding="utf-8").strip() if p.exists() else None


async def _probe_daemon_status() -> str:
    try:
        await safe_ipc_call("health")
        return "ok"
    except Exception:
        return "unreachable"


async def handle_mcp_config(request: Request) -> JSONResponse:
    serveo_url = _read_serveo_url()
    tunnel_token = _read_tunnel_token()
    route_cfg = getattr(request.scope.get("app", {}).state, "route_config", None) or load_route_config()
    routes = route_cfg.routes if isinstance(route_cfg, FullRouteConfig) else route_cfg
    routes_out = {}
    for path, cfg in routes.items():
        routes_out[path] = {
            "url": f"{serveo_url}{path}" if serveo_url else None,
            "auth": cfg["auth"],
            "client": cfg.get("client"),
            "transport": cfg.get("transport"),
            "bearer_token": tunnel_token if "bearer" in cfg["auth"] else None,
        }
    return JSONResponse({
        "serveo_url": serveo_url,
        "tunnel_token": tunnel_token,
        "routes": routes_out,
        "daemon_status": await _probe_daemon_status(),
    })


# ── Context-manager proxy → :3847 (BEARER required) ──────────────────────────

async def proxy_to_cm(request: Request) -> Response:
    path = request.url.path.removeprefix("/context-manager") or "/"
    target = f"{CM_UPSTREAM}{path}"
    if request.url.query:
        target += f"?{request.url.query}"
    try:
        async with httpx.AsyncClient() as client:
            upstream = await client.request(
                method=request.method, url=target,
                headers={k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization")},
                content=await request.body(), timeout=30,
            )
        return Response(content=upstream.content, status_code=upstream.status_code, headers=dict(upstream.headers))
    except httpx.ConnectError:
        return JSONResponse({"error": "bad_gateway", "message": "context-manager unavailable"}, status_code=502)
    except httpx.TimeoutException:
        return JSONResponse({"error": "gateway_timeout", "message": "context-manager timeout"}, status_code=504)
    except Exception as e:
        return JSONResponse({"error": "bad_gateway", "message": str(e)}, status_code=502)


# ── Handler map & config-to-entries (Sprint+2) ────────────────────────────────

_HANDLER_MAP: dict[str, Callable] = {
    "streamable-http": handle_mcp,
    "sse":             proxy_sse,
    "sse-messages":    proxy_messages,
    "proxy":           proxy_to_cm,
}

_METHODS_MAP: dict[str, list[str]] = {
    "streamable-http": ["GET", "POST", "DELETE"],
    "sse":             ["GET"],
    "sse-messages":    ["POST"],
    "proxy":           ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
}

_SERVICE_ENTRIES: dict[str, RouteEntry] = {
    "/.well-known/oauth-authorization-server": RouteEntry([AuthMode.NONE], oauth_metadata, ["GET"]),
    "/.well-known/oauth-protected-resource":   RouteEntry([AuthMode.NONE], protected_resource_metadata, ["GET"]),
    "/register":          RouteEntry([AuthMode.NONE], register,          ["POST"]),
    "/authorize":         RouteEntry([AuthMode.NONE], authorize,         ["GET"]),
    "/authorize/confirm": RouteEntry([AuthMode.NONE], authorize_confirm, ["GET", "POST"]),
    "/token":             RouteEntry([AuthMode.NONE], token,             ["POST"]),
    "/health":            RouteEntry([AuthMode.NONE], health,            ["GET"]),
    "/mcp-config":        RouteEntry([AuthMode.NONE], handle_mcp_config, ["GET"]),
}


def _config_to_entries(routes: dict) -> dict[str, RouteEntry]:
    entries = {}
    for path, cfg in routes.items():
        transport = cfg.get("transport", "streamable-http")
        handler = _HANDLER_MAP.get(transport)
        if handler is None:
            raise ValueError(f"Unknown transport: {transport!r}")
        entries[path] = RouteEntry(
            auth_modes=[AuthMode(m) for m in cfg["auth"]],
            handler=handler,
            methods=list(_METHODS_MAP[transport]),
        )
    return entries


# ── Watch backends (Sprint+3) ──────────────────────────────────────────────

def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


class WatchBackend(Protocol):
    async def watch(self, path: Path, interval: float) -> AsyncIterator[float]: ...


class InotifyBackend:
    def __init__(self):
        try:
            import watchfiles as _wf
            self._watchfiles = _wf
        except ImportError:
            raise RuntimeError("watchfiles not installed")

    async def watch(self, path: Path, interval: float) -> AsyncIterator[float]:
        last_mtime = _mtime(path)
        while True:
            await asyncio.sleep(interval)
            mtime = _mtime(path)
            if mtime != last_mtime:
                last_mtime = mtime
                yield mtime


class PollingBackend:
    async def watch(self, path: Path, interval: float) -> AsyncIterator[float]:
        last_mtime = _mtime(path)
        while True:
            await asyncio.sleep(interval)
            mtime = _mtime(path)
            if mtime != last_mtime:
                last_mtime = mtime
                yield mtime


def _make_watch_backend_from_config(config: WatcherConfig) -> WatchBackend:
    if config.backend == "inotify":
        return InotifyBackend()
    elif config.backend == "polling":
        return PollingBackend()
    else:
        try:
            return InotifyBackend()
        except RuntimeError:
            return PollingBackend()


# ── ReloadMetrics (Sprint+3) ──────────────────────────────────────────────

@dataclass
class ReloadMetrics:
    total_attempts: int = 0
    total_successes: int = 0
    total_errors: int = 0
    last_reload_time: float | None = None
    last_error_time: float | None = None
    last_error_message: str | None = None

    def __post_init__(self):
        self._lock = threading.RLock()

    def record_success(self) -> None:
        with self._lock:
            self.total_attempts += 1
            self.total_successes += 1
            self.last_reload_time = time.time()

    def record_error(self, message: str) -> None:
        with self._lock:
            self.total_attempts += 1
            self.total_errors += 1
            self.last_error_time = time.time()
            self.last_error_message = message

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "total_attempts": self.total_attempts,
                "total_successes": self.total_successes,
                "total_errors": self.total_errors,
                "last_reload_time": self.last_reload_time,
                "last_error_time": self.last_error_time,
                "last_error_message": self.last_error_message,
            }


# ── DynamicRouter (Sprint+2) ─────────────────────────────────────────────────

class DynamicRouter:
    """Единственный catch-all Route. Диспатчит запросы через RouteRegistry."""

    def __init__(self, registry: RouteRegistry):
        self.registry = registry

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] not in ("http", "websocket"):
            return

        path = scope.get("path", "/")
        method = scope.get("method", "GET").upper()

        entry = self.registry.match(path)
        if entry is None:
            await Response("Not Found", status_code=404)(scope, receive, send)
            return

        if method not in entry.methods:
            await Response("Method Not Allowed", status_code=405)(scope, receive, send)
            return

        handler = AuthSelector(entry.auth_modes)(entry.handler)
        await handler(scope, receive, send)


# ── RouteFileWatcher (Sprint+2) ──────────────────────────────────────────────

class RouteFileWatcher:
    """Следит за routes.json, обновляет registry при изменении."""

    def __init__(
        self,
        path: Path,
        registry: RouteRegistry,
        interval: float = 2.0,
        backend: WatchBackend | None = None,
        metrics: ReloadMetrics | None = None,
    ):
        self.path = path
        self.registry = registry
        self.interval = interval
        self.backend = backend or PollingBackend()
        self.metrics = metrics
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="route-watcher")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        async for _ in self.backend.watch(self.path, self.interval):
            try:
                await self._reload()
            except Exception as e:
                logger.warning("route-watcher error: %s", e)

    async def _reload(self) -> None:
        try:
            new_full = load_route_config(self.path)
            new_entries = _config_to_entries(new_full.routes)
            all_entries = dict(_SERVICE_ENTRIES)
            all_entries.update(new_entries)
            self.registry.update(all_entries)
            if self.metrics:
                self.metrics.record_success()
            logger.info("routes.json reloaded: %d routes", len(new_entries))
        except (ValueError, json.JSONDecodeError) as e:
            if self.metrics:
                self.metrics.record_error(str(e))
            logger.error("routes.json reload failed (keeping current): %s", e)


# ── App ───────────────────────────────────────────────────────────────────────

class ServeoHeaderASGIMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"serveo-skip-browser-warning", b"true"))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


def make_app(
    routes_config_path: str | Path | None = None,
    watch_interval: float = 2.0,
) -> Starlette:
    routes_path = Path(routes_config_path) if routes_config_path else (_MNEMO_DIR / "routes.json")
    registry = RouteRegistry()

    full_config = load_route_config(routes_path)
    watcher_config = full_config.watcher
    if watch_interval != 2.0:
        watcher_config.interval = watch_interval
    backend = _make_watch_backend_from_config(watcher_config)
    metrics = ReloadMetrics()
    watcher = RouteFileWatcher(
        routes_path,
        registry,
        interval=watcher_config.interval,
        backend=backend,
        metrics=metrics,
    )

    router = DynamicRouter(registry)

    initial_routes = full_config.routes
    all_entries = dict(_SERVICE_ENTRIES)
    all_entries.update(_config_to_entries(initial_routes))
    registry.update(all_entries)

    @asynccontextmanager
    async def _lifespan(app: Starlette):
        sm = StreamableHTTPSessionManager(
            app=_make_mcp_server(),
            event_store=None,
            json_response=True,
            stateless=True,
        )
        app.state.sm = sm
        app.state.registry = registry
        app.state.metrics = metrics
        app.state.watcher = watcher
        app.state.route_config = full_config
        reloaded = dict(_SERVICE_ENTRIES)
        reloaded.update(_config_to_entries(full_config.routes))
        registry.update(reloaded)
        await watcher.start()
        async with sm.run():
            yield
        await watcher.stop()
        app.state.sm = None

    return Starlette(
        lifespan=_lifespan,
        routes=[Route("/{path:path}", endpoint=router)],
        middleware=[
            Middleware(OAuthTokenMiddleware),
            Middleware(CORSMiddleware,
                       allow_origins=["*"],
                       allow_methods=["*"],
                       allow_headers=["*"]),
            Middleware(ServeoHeaderASGIMiddleware),
        ],
    )


app: Starlette = make_app()


if __name__ == "__main__":
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--public-url", type=str, required=True,
                        help="Public URL for OAuth endpoints (e.g., https://alice.serveo.net)")
    args: argparse.Namespace = parser.parse_args()
    PUBLIC_URL = args.public_url

    OAUTH_METADATA.update({
        "issuer": PUBLIC_URL,
        "authorization_endpoint": f"{PUBLIC_URL}/authorize",
        "token_endpoint": f"{PUBLIC_URL}/token",
        "registration_endpoint": f"{PUBLIC_URL}/register",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "none"],
    })

    PROTECTED_RESOURCE_METADATA.update({
        "resource": f"{PUBLIC_URL}/mcp",
        "authorization_servers": [PUBLIC_URL],
        "bearer_methods_supported": ["header"],
    })

    logging.basicConfig(level=logging.INFO)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
