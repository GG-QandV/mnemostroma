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

# ── Metrics (in-process counters, reset on restart) ──────────────────

_metrics: dict[str, int] = {
    "requests":  0,
    "observed":  0,
    "skipped":   0,
    "errors":    0,
}


def _current_session() -> str:
    try:
        sid = _SESSION_FILE.read_text(encoding="utf-8").strip()
        if sid:
            return sid
    except OSError:
        pass
    sid = f"passthrough-{date.today().isoformat()}"
    logger.warning("current_session missing — using fallback: %s", sid)
    return sid


async def _observe(text: str) -> None:
    if not text.strip():
        return
    try:
        await _ipc_call("observe", {"session_id": _current_session(), "text": text})
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
        upstream_req  = client.build_request(request.method, url, headers=headers, content=body)
        upstream_resp = await client.send(upstream_req, stream=True)
        content_type  = upstream_resp.headers.get("content-type", "")

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
                    # Close upstream connection after generator is exhausted or aborted
                    await upstream_resp.aclose()
                    await client.aclose()

            return StreamingResponse(
                _stream(),
                status_code=upstream_resp.status_code,
                headers=dict(upstream_resp.headers),
                media_type=content_type,
            )

        else:
            # JSON path: read body fully before closing client
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

    except httpx.ConnectError as exc:
        await client.aclose()
        _metrics["errors"] += 1
        logger.error("upstream connect failed: %s", exc)
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
