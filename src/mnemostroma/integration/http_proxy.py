# SPDX-License-Identifier: FSL-1.1-MIT
"""HTTP Reverse Proxy — transparent agent I/O interception.

BEFORE request → IPC "inject"      → <memory_context> in system prompt
AFTER response → IPC "outbox_put" → Observer writes to RAM/SQLite

Agent: ANTHROPIC_BASE_URL=http://127.0.0.1:8767

Reliability:
  • Circuit Breaker — fail-open if daemon is unavailable
  • SO_REUSEPORT   — fast restart without "port in use"
  • streaming finally — Observer receives text even on disconnect
  • Correlation ID  — stable session_id via X-Session-Id
"""
import asyncio
import json
import logging
import os
import socket
import sys
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import httpx
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route
import uvicorn

from mnemostroma.ipc_pool import IPCPool
from mnemostroma.circuit_breaker import CircuitBreaker

logger     = logging.getLogger("mnemostroma.http_proxy")
_ANTHROPIC = "https://api.anthropic.com"

_MNEMO_DIR  = Path.home() / ".mnemostroma"
_PROXY_PID  = _MNEMO_DIR / "proxy.pid"
_SOCKET     = _MNEMO_DIR / "daemon.sock"

_pool: IPCPool | None = None
_cb_inject  = CircuitBreaker("inject",  failure_threshold=3, recovery_timeout=30)
_cb_observe = CircuitBreaker("observe", failure_threshold=5, recovery_timeout=10)


# ── Lifespan ──────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app):
    global _pool
    _MNEMO_DIR.mkdir(parents=True, exist_ok=True)
    _PROXY_PID.write_text(str(os.getpid()))

    # Wait for socket up to 30s — daemon might start slightly later
    for attempt in range(15):
        if _SOCKET.exists():
            break
        logger.info(f"Waiting for daemon socket... ({attempt + 1}/15)")
        await asyncio.sleep(2)
    else:
        logger.warning("Daemon socket not found — starting in degraded mode")

    _pool = IPCPool(str(_SOCKET), size=4)
    try:
        await _pool.start()
    except Exception as e:
        logger.warning(f"IPC pool start failed ({e}) — Circuit Breaker will handle")

    logger.info("HTTP Proxy ready on http://127.0.0.1:8767")
    yield

    _PROXY_PID.unlink(missing_ok=True)
    await _pool.stop()


# ── Correlation ID ────────────────────────────────────────────────────

def _get_or_create_sid(request: Request) -> tuple[str, bool]:
    """Return (session_id, is_new).
    is_new=True — need to provide X-Session-Id in response headers.
    """
    for h in ("x-session-id", "x-mnemo-session", "x-correlation-id"):
        if sid := request.headers.get(h):
            return sid, False
    return "proxy_" + uuid.uuid4().hex[:16], True


# ── Helpers ───────────────────────────────────────────────────────────

def _last_user_text(messages: list) -> str:
    for m in reversed(messages):
        if m.get("role") != "user":
            continue
        c = m.get("content", "")
        if isinstance(c, str):
            return c[:500]
        if isinstance(c, list):
            return " ".join(
                b.get("text", "") for b in c if b.get("type") == "text"
            )[:500]
    return ""


def _forward_headers(request: Request) -> dict:
    skip = {"host", "content-length", "transfer-encoding"}
    return {k: v for k, v in request.headers.items() if k.lower() not in skip}


# ── Memory inject (fail-open) ─────────────────────────────────────────

async def _inject_memory(body: dict, sid: str) -> dict:
    xml = await _cb_inject.call(
        _pool.call,
        "inject",
        {"user_message": _last_user_text(body.get("messages", [])),
         "session_id": sid},
        fallback=None,
    )
    if not xml:
        return body  # fail-open: continue without memory

    body = dict(body)
    sys_prompt = body.get("system", "")
    if isinstance(sys_prompt, list):
        body["system"] = sys_prompt + [{"type": "text", "text": f"\n\n{xml}"}]
    else:
        body["system"] = (sys_prompt + "\n\n" + xml).strip()
    return body


# ── Observer feed (via Outbox, fail-open) ─────────────────────────────

async def _observe(text: str, sid: str) -> None:
    if not text or len(text.strip()) < 20:
        return
    await _cb_observe.call(
        _pool.call,
        "outbox_put",
        {"session_id": sid, "text": text},
        fallback=None,  # fail-open: data loss on total daemon failure
    )


# ── Proxy handlers ────────────────────────────────────────────────────

async def proxy_messages(request: Request) -> Response:
    raw = await request.body()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        return Response("Bad JSON", status_code=400)

    sid, is_new = _get_or_create_sid(request)
    body        = await _inject_memory(body, sid)
    streaming   = body.get("stream", False)
    fwd         = _forward_headers(request)
    extra       = {"X-Session-Id": sid} if is_new else {}

    async with httpx.AsyncClient(
        base_url=_ANTHROPIC,
        timeout=httpx.Timeout(connect=10, read=300, write=30, pool=10),
    ) as client:
        if streaming:
            return await _handle_stream(client, body, fwd, sid, extra)
        else:
            return await _handle_simple(client, body, fwd, sid, extra)


async def _handle_simple(client, body, headers, sid, extra) -> Response:
    resp = await client.post("/v1/messages", json=body, headers=headers)
    try:
        data = resp.json()
        text = "".join(
            b.get("text", "") for b in data.get("content", [])
            if b.get("type") == "text"
        )
        if text:
            asyncio.create_task(_observe(text, sid))
    except Exception:
        pass
    out = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in ("content-encoding", "transfer-encoding")
    }
    out.update(extra)
    return Response(
        content    = resp.content,
        status_code= resp.status_code,
        headers    = out,
        media_type = resp.headers.get("content-type", "application/json"),
    )


async def _handle_stream(client, body, headers, sid, extra) -> StreamingResponse:
    collected: list[str] = []

    async def generate() -> AsyncIterator[bytes]:
        try:
            async with client.stream(
                "POST", "/v1/messages", json=body, headers=headers
            ) as resp:
                async for chunk in resp.aiter_bytes():
                    # Parse SSE to collect text
                    try:
                        for line in chunk.decode(errors="replace").splitlines():
                            if not line.startswith("data: "):
                                continue
                            payload = line[6:].strip()
                            if payload in ("", "[DONE]"):
                                continue
                            ev = json.loads(payload)
                            if ev.get("type") == "content_block_delta":
                                d = ev.get("delta", {})
                                if d.get("type") == "text_delta":
                                    collected.append(d.get("text", ""))
                    except Exception:
                        pass
                    yield chunk
        finally:
            # finally guarantees call even on client disconnect
            asyncio.create_task(_observe("".join(collected), sid))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
            "Connection":       "keep-alive",
            **extra,
        },
    )


async def health(request: Request) -> Response:
    try:
        await _pool.call("ctx_active", {})
        return Response('{"status":"ok"}', media_type="application/json")
    except Exception as e:
        return Response(
            json.dumps({"status": "error", "detail": str(e)}),
            status_code=503,
            media_type="application/json",
        )


# ── App ───────────────────────────────────────────────────────────────

app = Starlette(
    lifespan=lifespan,
    routes=[
        Route("/v1/messages", proxy_messages, methods=["POST"]),
        Route("/health",      health,         methods=["GET"]),
    ],
)


def _make_socket(port: int) -> socket.socket:
    """SO_REUSEPORT — fast restart without "Address already in use"."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    sock.bind(("127.0.0.1", port))
    return sock


async def run(port: int = 8767) -> None:
    logging.basicConfig(level=logging.INFO)
    sock = _make_socket(port)

    _cert = _MNEMO_DIR / "certs" / "passthrough-cert.pem"
    _key  = _MNEMO_DIR / "certs" / "passthrough-key.pem"
    _tls  = _cert.exists() and _key.exists()

    cfg = uvicorn.Config(
        app,
        fd            = sock.fileno(),
        log_level     = "warning",
        access_log    = False,
        **({"ssl_certfile": str(_cert), "ssl_keyfile": str(_key)} if _tls else {}),
    )
    srv = uvicorn.Server(cfg)
    proto = "https" if _tls else "http"
    logger.info(f"Proxy → {proto}://127.0.0.1:{port}  (TLS={'yes' if _tls else 'no'})")
    logger.info(f"Agent env: ANTHROPIC_BASE_URL={proto}://127.0.0.1:{port}")
    try:
        await srv.serve()
    finally:
        sock.close()


if __name__ == "__main__":
    asyncio.run(run(int(sys.argv[1]) if len(sys.argv) > 1 else 8767))
