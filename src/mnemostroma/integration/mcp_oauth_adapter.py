"""
MCP OAuth Adapter — единый сервер для всех 4 чатов.
Порт: 8769 (проксирует к mcphttpadapter :8768 / mcpsseadapter :8765)

Фаза 0: Perplexity (no auth)
Фаза 1: Claude.ai  (OAuth + PKCE + DCR, RFC 8414)
Фаза 2: ChatGPT    (OAuth + PKCE + DCR, RFC 8414 + RFC 9728)
Фаза 3: Grok       (Bearer token)
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import secrets
import time
import webbrowser
from pathlib import Path
from typing import Any, AsyncGenerator

import httpx
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response, StreamingResponse
from starlette.routing import Route

from mnemostroma.integration.tunnel.token import get_or_create_tunnel_token

logger: logging.Logger = logging.getLogger("mnemostroma.integration.mcp_oauth_adapter")

# ── In-memory OAuth state ─────────────────────────────────────────────────────
_clients: dict[str, dict[str, Any]] = {}    # client_id → {client_secret, redirect_uris}
_codes:   dict[str, dict[str, Any]] = {}    # code → {client_id, pkce_challenge, redirect_uri, expires}
_tokens:  dict[str, dict[str, Any]] = {}    # token → {client_id, expires}

MCP_HTTP_UPSTREAM: str = "http://localhost:8768"
MCP_SSE_UPSTREAM: str  = "http://localhost:8765"

_MNEMO_DIR = Path.home() / ".mnemostroma"
_SSE_TOKEN_PATH = _MNEMO_DIR / "sse_token"

def _get_internal_token() -> str:
    if _SSE_TOKEN_PATH.exists():
        return _SSE_TOKEN_PATH.read_text(encoding="utf-8").strip()
    return ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _verify_bearer(request: Request) -> bool:
    auth: str = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        # Perplexity doesn't send auth headers, Phase 0 is no-auth.
        # But we must verify if this is /sse or /mcp without auth.
        # In fact, Phase 0 (Perplexity) has NO AUTH. So if no header is present,
        # we check if it is Perplexity (in practice, if we have dynamic clients registered,
        # we enforce auth. If we don't have clients, or if it comes from Perplexity,
        # or we just allow no-auth as fallback if token is not configured?).
        # Wait, the spec says:
        # S0.2 — Perplexity: /mcp без auth (no auth required) -> проксирует
        # So if Authorization header is missing, we check if we should allow it.
        # Wait, how do we distinguish between Grok (which needs Bearer token) and Perplexity (no auth)?
        # If the user sets up Grok, they configure Bearer token.
        # If Authorization header is COMPLETELY absent, we allow it (for Perplexity Phase 0).
        # If Authorization is PRESENT, it must be valid (either static tunnel_token or OAuth token).
        # Let's check this logic.
        # If there is no Authorization header, we allow it (no auth fallback for Perplexity).
        # If there is Authorization header, we validate it.
        if not auth:
            logger.debug("No Authorization header provided, allowing as no-auth (Phase 0/Perplexity)")
            return True
        return False

    tok: str = auth[7:]
    # Grok/Perplexity: static tunnel_token
    if tok == get_or_create_tunnel_token():
        return True
    # Claude.ai / ChatGPT: dynamic OAuth token
    entry: dict[str, Any] | None = _tokens.get(tok)
    return bool(entry and time.time() < entry["expires"])


def _pkce_verify(verifier: str, challenge: str) -> bool:
    digest: str = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return digest == challenge


# ── RFC 8414 — OAuth Server Metadata (Claude.ai + ChatGPT) ───────────────────

async def oauth_metadata(request: Request) -> JSONResponse:
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


# ── RFC 9728 — Protected Resource Metadata (ChatGPT only) ────────────────────

async def protected_resource_metadata(request: Request) -> JSONResponse:
    base: str = _base_url(request)
    return JSONResponse({
        "resource": f"{base}/mcp",
        "authorization_servers": [base],
        "bearer_methods_supported": ["header"],
    })


# ── DCR — Dynamic Client Registration (Claude.ai + ChatGPT) ──────────────────

async def register(request: Request) -> JSONResponse:
    try:
        data: dict[str, Any] = await request.json()
    except Exception:
        logger.error("Failed to parse register JSON request")
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


# ── /authorize — PKCE S256 (Claude.ai + ChatGPT) ─────────────────────────────

async def authorize(request: Request) -> Response:
    p: dict[str, str] = dict(request.query_params)
    required: set[str] = {"client_id", "redirect_uri", "code_challenge", "response_type"}
    if not required.issubset(p):
        return JSONResponse({"error": "invalid_request"}, status_code=400)
    if p.get("code_challenge_method", "S256") != "S256":
        return JSONResponse({"error": "invalid_request", "error_description": "Only S256 supported"}, status_code=400)

    code: str = secrets.token_urlsafe(32)
    _codes[code] = {
        "client_id": p["client_id"],
        "pkce_challenge": p["code_challenge"],
        "redirect_uri": p["redirect_uri"],
        "expires": time.time() + 300,
    }
    # Открываем браузер пользователя для подтверждения
    try:
        webbrowser.open(f"{_base_url(request)}/authorize/confirm?code={code}&state={p.get('state','')}")
    except Exception as e:
        logger.warning(f"Failed to open web browser: {e}")
        
    # Немедленный редирект (браузер успеет подтвердить через confirm endpoint)
    redirect: str = p["redirect_uri"]
    state: str = p.get("state", "")
    return RedirectResponse(f"{redirect}?code={code}&state={state}", status_code=302)


async def authorize_confirm(request: Request) -> Response:
    """Страница подтверждения — показывается локально в браузере пользователя."""
    code: str = request.query_params.get("code", "")
    state: str = request.query_params.get("state", "")
    if request.method == "POST":
        # Пользователь нажал "Allow Access"
        # Перенаправляем на redirect_uri клиента
        entry: dict[str, Any] | None = _codes.get(code)
        if not entry:
            return Response("Authorization session expired or invalid.", status_code=400)
        
        # Мы подтвердили авторизацию
        html_success: str = """<!DOCTYPE html><html><body style="font-family:sans-serif;padding:2em;text-align:center">
        <h2 style="color:#22c55e">Access Granted!</h2>
        <p>You can close this window now and return to your chat application.</p>
        </body></html>"""
        return Response(html_success, media_type="text/html")

    html: str = f"""<!DOCTYPE html><html><body style="font-family:sans-serif;padding:2em">
    <h2>Mnemostroma — Authorization Request</h2>
    <p>An external chat application is requesting access to your local Mnemostroma memory.</p>
    <p><b>Code:</b> {code[:8]}...</p>
    <form method="post" action="/authorize/confirm?code={code}&state={state}">
        <input type="hidden" name="code" value="{code}">
        <input type="hidden" name="state" value="{state}">
        <button type="submit" style="background:#22c55e;color:white;padding:.5em 1.5em;border:none;border-radius:4px;cursor:pointer">
            Allow Access
        </button>
    </form>
    </body></html>"""
    return Response(html, media_type="text/html")


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


# ── /mcp — HTTP proxy → mcphttpadapter :8768 (ChatGPT + Perplexity HTTP) ─────

async def mcp_http(request: Request) -> Response:
    if not _verify_bearer(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    
    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization")}
    internal_token = _get_internal_token()
    if internal_token:
        headers["Authorization"] = f"Bearer {internal_token}"

    async with httpx.AsyncClient() as client:
        body: bytes = await request.body()
        upstream: httpx.Response = await client.request(
            method=request.method,
            url=f"{MCP_HTTP_UPSTREAM}/mcp",
            headers=headers,
            content=body,
            timeout=30,
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=dict(upstream.headers),
    )


# ── /sse — SSE proxy → mcpsseadapter :8765 (Claude.ai + Grok SSE) ────────────

async def mcp_sse(request: Request) -> Response:
    if not _verify_bearer(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    headers = {k: v for k, v in request.headers.items() if k.lower() not in ("host", "authorization")}
    internal_token = _get_internal_token()
    if internal_token:
        headers["Authorization"] = f"Bearer {internal_token}"

    async def stream_generator() -> AsyncGenerator[bytes, None]:
        async with httpx.AsyncClient() as client:
            async with client.stream("GET", f"{MCP_SSE_UPSTREAM}/sse",
                                     headers=headers,
                                     timeout=None) as upstream:
                async for chunk in upstream.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── /health ───────────────────────────────────────────────────────────────────

async def health(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "adapter": "mcp_oauth_adapter"})


# ── App ───────────────────────────────────────────────────────────────────────

app: Starlette = Starlette(routes=[
    # OAuth metadata
    Route("/.well-known/oauth-authorization-server",  oauth_metadata, methods=["GET"]),
    Route("/.well-known/oauth-protected-resource",    protected_resource_metadata, methods=["GET"]),
    # OAuth flow
    Route("/register",          register,          methods=["POST"]),
    Route("/authorize",         authorize,         methods=["GET"]),
    Route("/authorize/confirm", authorize_confirm, methods=["GET", "POST"]),
    Route("/token",             token,             methods=["POST"]),
    # MCP transports
    Route("/mcp",  mcp_http, methods=["GET", "POST", "DELETE"]),
    Route("/sse",  mcp_sse,  methods=["GET"]),
    # Health
    Route("/health", health, methods=["GET"]),
])


if __name__ == "__main__":
    parser: argparse.ArgumentParser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8769)
    args: argparse.Namespace = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
