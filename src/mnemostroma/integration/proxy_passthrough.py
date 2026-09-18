# SPDX-License-Identifier: FSL-1.1-MIT
"""Passthrough HTTPS proxy for Claude Code → Anthropic API.

Forwards all requests transparently to api.anthropic.com.
For POST /v1/messages: collects response text and fires observe() to daemon
so Observer can index the conversation without modifying system prompt or body.

Entry point: make_passthrough_app() — called from mcp_sse_adapter.run().
Requires: mnemostroma[sse] (httpx, starlette, uvicorn).

Session binding: reads ~/.mnemostroma/current_session (written by mcp_stdio_adapter
on startup). Falls back to date-based anonymous session if file is absent.
"""
import asyncio
import json
import logging
from datetime import date
from pathlib import Path

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

from .mcp_stdio_adapter import _ipc_call

logger = logging.getLogger("mnemostroma.passthrough")

_MNEMO_DIR    = Path.home() / ".mnemostroma"
_SESSION_FILE = _MNEMO_DIR / "current_session"
_UPSTREAM     = "https://api.anthropic.com"

# ── Failover (Anthropic → OpenModel) ─────────────────────────────────
# Mid-session resilience: when Anthropic fails between requests, retry the
# same body against api.openmodel.ai (deepseek-v4-flash). Only fires while
# mnemostroma is running and before the first response byte reaches the client.

_FALLBACK_UPSTREAM   = "https://api.openmodel.ai"
_FALLBACK_MODEL      = "deepseek-v4-flash"
_FALLBACK_KEY_ENV    = "OPENMODEL_API_KEY"
_FALLBACK_STATUSES   = frozenset({429, 500, 502, 503, 529})
_FALLBACK_KEY: str | None = None


def _load_fallback_key() -> str | None:
    """Read the OpenModel key once at startup: env first, else ~/.hermes/.env."""
    import os

    val = os.environ.get(_FALLBACK_KEY_ENV, "").strip()
    if val:
        return val
    env_file = Path.home() / ".hermes" / ".env"
    try:
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(f"{_FALLBACK_KEY_ENV}="):
                return line.split("=", 1)[1].strip()
    except OSError:
        pass
    return None


# ── Metrics (in-process counters, reset on restart) ──────────────────

_metrics: dict[str, int] = {
    "requests":  0,
    "observed":  0,
    "skipped":   0,
    "errors":    0,
    "failover_attempts": 0,
    "failover_ok":       0,
    "failover_failed":   0,
}

_session_id: str | None = None


async def _resolve_session() -> str:
    """Get session_id from daemon via IPC or fallback to file/date."""
    try:
        # Try IPC first
        result = await asyncio.wait_for(_ipc_call("ctx_active", {}), timeout=3.0)
        sid = (result or {}).get("session_id", "")
        if sid:
            return sid
    except Exception as exc:
        logger.debug("ctx_active IPC failed: %s", exc)

    # Fallback 1: File written by mcp_stdio_adapter
    try:
        sid = _SESSION_FILE.read_text(encoding="utf-8").strip()
        if sid and not sid.startswith("passthrough-"):
            return sid
    except OSError:
        pass

    # Fallback 2: Date-based anonymous session
    sid = f"passthrough-{date.today().isoformat()}"
    return sid


async def _observe(text: str) -> None:
    if not text.strip():
        return
    try:
        await _ipc_call("observe", {"session_id": await _resolve_session(), "text": text})
        _metrics["observed"] += 1
    except Exception as exc:
        _metrics["errors"] += 1
        logger.debug("observe failed: %s", exc)


def _extract_sse_text(chunk: str) -> str:
    """Extract delta.text from one SSE chunk (may contain multiple data: lines)."""
    parts: list[str] = []
    for line in chunk.splitlines():
        if not line.startswith("data:"):
            continue
        raw = line[5:].strip()
        if raw in ("[DONE]", ""):
            continue
        try:
            ev = json.loads(raw)
            parts.append(ev.get("delta", {}).get("text", ""))
        except (json.JSONDecodeError, AttributeError):
            pass
    return "".join(parts)


def _is_failover_status(status: int | None) -> bool:
    return status in _FALLBACK_STATUSES


def _make_fallback_headers(headers: dict[str, str]) -> dict[str, str]:
    """Rebuild headers for the OpenModel retry: x-api-key, drop authorization."""
    out = {k: v for k, v in headers.items() if k.lower() != "authorization"}
    if _FALLBACK_KEY:
        out["x-api-key"] = _FALLBACK_KEY
    return out


def _make_fallback_body(body: bytes) -> bytes:
    """Rewrite model in the request body to deepseek-v4-flash."""
    if not body:
        return body
    try:
        payload = json.loads(body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body
    if isinstance(payload, dict):
        payload["model"] = _FALLBACK_MODEL
    return json.dumps(payload).encode("utf-8")


async def _try_failover(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes,
    reason: str,
) -> httpx.Response | None:
    """Retry the request against OpenModel. Returns response or None on failure."""
    global _FALLBACK_KEY
    if _FALLBACK_KEY is None:
        _FALLBACK_KEY = _load_fallback_key()
    if not _FALLBACK_KEY:
        return None

    _metrics["failover_attempts"] += 1
    fb_headers = _make_fallback_headers(headers)
    fb_body = _make_fallback_body(body)
    fb_url = (
        _FALLBACK_UPSTREAM + url[len(_UPSTREAM):]
        if url.startswith(_UPSTREAM)
        else url
    )

    try:
        fb_req = client.build_request(
            method, fb_url, headers=fb_headers, content=fb_body
        )
        fb_resp = await client.send(fb_req, stream=True)
        if _is_failover_status(fb_resp.status_code):
            _metrics["failover_failed"] += 1
            logger.info(
                "failover: %s → %s failed (status=%s)",
                reason, _FALLBACK_MODEL, fb_resp.status_code,
            )
            await fb_resp.aclose()
            return None
        _metrics["failover_ok"] += 1
        logger.info(
            "failover: %s → %s ok (status=%s)",
            reason, _FALLBACK_MODEL, fb_resp.status_code,
        )
        return fb_resp
    except Exception as exc:
        _metrics["failover_failed"] += 1
        logger.info(
            "failover: %s → %s failed (%s)",
            reason, _FALLBACK_MODEL, type(exc).__name__,
        )
        return None


async def _respond_with(
    client: httpx.AsyncClient,
    upstream_resp: httpx.Response,
    is_messages: bool,
) -> Response:
    """Build the client response from an upstream response (stream or JSON)."""
    content_type = upstream_resp.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        buf: list[str] = []

        async def _stream():
            try:
                async for chunk in upstream_resp.aiter_text():
                    yield chunk
                    if is_messages:
                        buf.append(_extract_sse_text(chunk))
                if is_messages and buf:
                    asyncio.create_task(_observe("".join(buf)))
            finally:
                await upstream_resp.aclose()
                await client.aclose()

        return StreamingResponse(
            _stream(),
            status_code=upstream_resp.status_code,
            headers=dict(upstream_resp.headers),
            media_type=content_type,
        )

    raw = await upstream_resp.aread()
    await client.aclose()
    if is_messages:
        try:
            payload = json.loads(raw)
            text = (payload.get("content") or [{}])[0].get("text", "")
            asyncio.create_task(_observe(text))
        except Exception:
            pass
    return Response(
        content=raw,
        status_code=upstream_resp.status_code,
        headers=dict(upstream_resp.headers),
        media_type=content_type,
    )


# ── Request handler ───────────────────────────────────────────────────

async def handle_request(request: Request) -> Response:
    _metrics["requests"] += 1

    body = await request.body()
    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in ("host", "accept-encoding")
    }
    headers["accept-encoding"] = "identity"

    url = _UPSTREAM + request.url.path
    if request.url.query:
        url += "?" + request.url.query

    is_messages = request.method == "POST" and "/v1/messages" in request.url.path
    if not is_messages:
        _metrics["skipped"] += 1

    # Client is NOT used as context manager here — for SSE we must keep the
    # connection alive after returning StreamingResponse. The generator takes
    # ownership of both upstream_resp and client and closes them in its finally block.
    client = httpx.AsyncClient(timeout=300)
    try:
        upstream_req = client.build_request(
            request.method, url, headers=headers, content=body
        )
        upstream_resp = await client.send(upstream_req, stream=True)

        # Failover: Anthropic down (5xx/429) or transport error before the first
        # byte reached the client → retry once against OpenModel.
        if (
            is_messages
            and _FALLBACK_KEY is not None
            and _is_failover_status(upstream_resp.status_code)
        ):
            await upstream_resp.aclose()
            fb = await _try_failover(
                client, request.method, url, headers, body,
                reason=f"status={upstream_resp.status_code}",
            )
            if fb is not None:
                upstream_resp = fb

        return await _respond_with(client, upstream_resp, is_messages)

    except httpx.ConnectError as exc:
        _metrics["errors"] += 1
        logger.error("upstream connect failed: %s", exc)

        # Failover on transport error (only for messages POST, only once).
        if is_messages and _FALLBACK_KEY is not None:
            fb = await _try_failover(
                client, request.method, url, headers, body,
                reason="ConnectError",
            )
            if fb is not None:
                return await _respond_with(client, fb, is_messages)

        await client.aclose()
        return Response(
            content=json.dumps({"error": "upstream unavailable", "detail": str(exc)}).encode(),
            status_code=502,
            media_type="application/json",
        )
    except Exception as exc:
        await client.aclose()
        _metrics["errors"] += 1
        logger.error("passthrough error: %s", exc, exc_info=True)
        return Response(
            content=json.dumps({"error": str(exc)}).encode(),
            status_code=500,
            media_type="application/json",
        )


# ── Health endpoint ───────────────────────────────────────────────────

async def handle_health(request: Request) -> Response:
    return Response(
        content=json.dumps({"status": "ok", "metrics": _metrics}).encode(),
        media_type="application/json",
    )


# ── App factory ───────────────────────────────────────────────────────

def make_passthrough_app() -> Starlette:
    return Starlette(routes=[
        Route("/health",      endpoint=handle_health),
        Route("/{path:path}", endpoint=handle_request,
              methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"]),
    ])
