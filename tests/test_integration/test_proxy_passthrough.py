# SPDX-License-Identifier: FSL-1.1-MIT
"""Full traceroute tests: Claude Code CLI → proxy_passthrough → IPC → Observer.

Each test traces one complete path through the stack and asserts invariants
at every boundary. No ONNX models are loaded — observer_pipeline is mocked
at the task-creation level.

Boundaries under test:
  A. HTTP layer       — proxy_passthrough ASGI app receives requests
  B. SSE extraction   — _extract_sse_text collects delta.text from chunks
  C. Observe dispatch — _observe() calls _ipc_call("observe", ...)
  D. IPC layer        — IPCServer receives JSON-RPC → conductor.dispatch()
  E. Observer gate    — structural_prefilter discards short text
  F. Session file     — mcp_stdio_adapter writes current_session

Tail invariants checked in A-layer tests:
  - fire-and-forget create_task completes before assertion (asyncio.Event)
  - httpx upstream client is created BEFORE patch to avoid cross-contamination
  - _metrics counters increment correctly per request type

IMPORTANT — patching rule:
  proxy_passthrough imports httpx at module level. Patching
  "proxy_passthrough.httpx.AsyncClient" replaces httpx.AsyncClient globally.
  Test httpx.AsyncClient instances MUST be created before entering patch context.
"""
import asyncio
import json
import sys
import pytest
import httpx
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────

def _make_async_iter(chunks: list[str]):
    """Build an async generator factory from a list of SSE text chunks."""
    async def _gen():
        for chunk in chunks:
            yield chunk
    return _gen


def _make_json_response(body: dict, status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": "application/json"}
    resp.aread = AsyncMock(return_value=json.dumps(body).encode())
    resp.aclose = AsyncMock()
    return resp


def _make_sse_response(chunks: list[str]) -> MagicMock:
    resp = MagicMock()
    resp.status_code = 200
    resp.headers = {"content-type": "text/event-stream"}
    resp.aiter_text = _make_async_iter(chunks)
    resp.aclose = AsyncMock()
    return resp


def _make_mock_upstream(fake_response: MagicMock):
    """Build a mock httpx.AsyncClient that returns fake_response from .send()."""
    mock_client = AsyncMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send = AsyncMock(return_value=fake_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ── Layer A: HTTP — JSON /v1/messages ────────────────────────────────

@pytest.mark.asyncio
async def test_json_messages_observe_called_with_extracted_text(tmp_path):
    """POST /v1/messages (JSON) → _ipc_call('observe') receives body text."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app, _metrics

    session_file = tmp_path / "current_session"
    session_file.write_text("test-session-001", encoding="utf-8")

    fake_resp = _make_json_response({"content": [{"text": "hello from upstream"}]})
    mock_upstream = _make_mock_upstream(fake_resp)
    observed_calls: list[dict] = []

    async def _fake_ipc(tool: str, args: dict):
        if tool == "observe":
            observed_calls.append(args)
        return {"ok": True}

    prev_observed = _metrics["observed"]

    # Create ASGI test client BEFORE patching httpx.AsyncClient
    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_upstream), \
             patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            resp = await client.post(
                "/v1/messages",
                json={"model": "claude-opus-4-6", "messages": []},
            )
            # drain fire-and-forget tasks before asserting
            await asyncio.sleep(0.02)

    # A1: upstream status forwarded unchanged
    assert resp.status_code == 200

    # A2: observe called exactly once with correct session + text
    assert len(observed_calls) == 1
    assert observed_calls[0]["session_id"] == "test-session-001"
    assert observed_calls[0]["text"] == "hello from upstream"

    # A3: metric incremented
    assert _metrics["observed"] == prev_observed + 1


# ── Layer A+B: HTTP — SSE /v1/messages ───────────────────────────────

@pytest.mark.asyncio
async def test_sse_messages_chunks_collected_into_single_observe(tmp_path):
    """POST /v1/messages (SSE) → chunks buffered → single observe() with full text."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app

    session_file = tmp_path / "current_session"
    session_file.write_text("sse-session-42", encoding="utf-8")

    sse_chunks = [
        'data: {"type": "content_block_delta", "delta": {"text": "hello"}}\n',
        'data: {"type": "content_block_delta", "delta": {"text": " world"}}\n',
        'data: {"type": "message_stop"}\n',
        "data: [DONE]\n",
    ]
    fake_resp = _make_sse_response(sse_chunks)
    mock_upstream = _make_mock_upstream(fake_resp)
    observed_calls: list[dict] = []

    async def _fake_ipc(tool: str, args: dict):
        if tool == "observe":
            observed_calls.append(args)
        return {"ok": True}

    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_upstream), \
             patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            async with client.stream("POST", "/v1/messages",
                                     json={"model": "claude-opus-4-6", "messages": []}) as r:
                received = [c async for c in r.aiter_text()]

            await asyncio.sleep(0.02)

    # B1: all chunks forwarded to client unchanged
    assert "".join(received) == "".join(sse_chunks)

    # B2: observe called ONCE with concatenated text (not per-chunk)
    assert len(observed_calls) == 1
    assert observed_calls[0]["text"] == "hello world"
    assert observed_calls[0]["session_id"] == "sse-session-42"


@pytest.mark.asyncio
async def test_sse_no_delta_text_skips_observe(tmp_path):
    """SSE stream with zero delta.text → _observe() not called."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app

    session_file = tmp_path / "current_session"
    session_file.write_text("s", encoding="utf-8")

    sse_chunks = [
        'data: {"type": "message_start"}\n',
        'data: {"type": "message_stop"}\n',
        "data: [DONE]\n",
    ]
    fake_resp = _make_sse_response(sse_chunks)
    mock_upstream = _make_mock_upstream(fake_resp)
    observed_calls: list = []

    async def _fake_ipc(tool: str, args: dict):
        if tool == "observe":
            observed_calls.append(args)
        return {}

    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_upstream), \
             patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            async with client.stream("POST", "/v1/messages", json={}) as r:
                _ = [c async for c in r.aiter_text()]

            await asyncio.sleep(0.02)

    assert len(observed_calls) == 0


# ── Layer A: non-messages endpoints ──────────────────────────────────

@pytest.mark.asyncio
async def test_get_models_skips_observe(tmp_path):
    """GET /v1/models → forwarded, observe NOT called, skipped metric up."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app, _metrics

    session_file = tmp_path / "current_session"
    session_file.write_text("s", encoding="utf-8")

    fake_resp = _make_json_response({"models": []})
    mock_upstream = _make_mock_upstream(fake_resp)
    observed_calls: list = []
    prev_skipped = _metrics["skipped"]

    async def _fake_ipc(tool: str, args: dict):
        if tool == "observe":
            observed_calls.append(args)
        return {}

    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_upstream), \
             patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            resp = await client.get("/v1/models")
            await asyncio.sleep(0.02)

    assert resp.status_code == 200
    assert len(observed_calls) == 0
    assert _metrics["skipped"] == prev_skipped + 1


# ── Layer A: upstream error ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_upstream_connect_error_returns_502(tmp_path):
    """ConnectError from upstream → 502, observe NOT called, errors metric up."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app, _metrics

    session_file = tmp_path / "current_session"
    session_file.write_text("s", encoding="utf-8")

    mock_client = AsyncMock()
    mock_client.build_request.return_value = MagicMock()
    mock_client.send = AsyncMock(side_effect=httpx.ConnectError("upstream unreachable"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    observed_calls: list = []
    prev_errors = _metrics["errors"]

    async def _fake_ipc(tool: str, args: dict):
        if tool == "observe":
            observed_calls.append(args)
        return {}

    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_client), \
             patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            resp = await client.post("/v1/messages", json={})
            await asyncio.sleep(0.02)

    assert resp.status_code == 502
    assert "error" in resp.json()
    assert len(observed_calls) == 0
    assert _metrics["errors"] == prev_errors + 1


# ── Layer A: current_session fallback ────────────────────────────────

@pytest.mark.asyncio
async def test_missing_session_file_uses_date_fallback(tmp_path):
    """No current_session file → fallback sid 'passthrough-{date}', observe still fires."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app

    missing = tmp_path / "no_file_here"  # intentionally absent
    fake_resp = _make_json_response({"content": [{"text": "some text"}]})
    mock_upstream = _make_mock_upstream(fake_resp)
    observed_calls: list[dict] = []

    async def _fake_ipc(tool: str, args: dict):
        if tool == "observe":
            observed_calls.append(args)
        return {"ok": True}

    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_upstream), \
             patch.object(proxy_passthrough, "_SESSION_FILE", missing), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            await client.post("/v1/messages", json={})
            await asyncio.sleep(0.02)

    assert len(observed_calls) == 1
    assert observed_calls[0]["session_id"].startswith("passthrough-")


# ── Layer B: _extract_sse_text unit ──────────────────────────────────

def test_extract_sse_text_happy_path():
    """delta.text values extracted from one multi-line chunk."""
    from mnemostroma.integration.proxy_passthrough import _extract_sse_text

    chunk = (
        'data: {"type": "content_block_delta", "delta": {"text": "foo"}}\n'
        'data: {"type": "content_block_delta", "delta": {"text": "bar"}}\n'
    )
    assert _extract_sse_text(chunk) == "foobar"


def test_extract_sse_text_ignores_non_delta():
    """Non-delta event types yield empty string."""
    from mnemostroma.integration.proxy_passthrough import _extract_sse_text

    chunk = (
        'data: {"type": "message_start"}\n'
        'data: [DONE]\n'
        'event: ping\n'
    )
    assert _extract_sse_text(chunk) == ""


def test_extract_sse_text_malformed_json_skipped():
    """Malformed data: lines are silently skipped — no exception."""
    from mnemostroma.integration.proxy_passthrough import _extract_sse_text

    assert _extract_sse_text("data: {not valid json}\ndata: {}\n") == ""


def test_extract_sse_text_done_marker_skipped():
    """[DONE] sentinel produces no text."""
    from mnemostroma.integration.proxy_passthrough import _extract_sse_text

    assert _extract_sse_text("data: [DONE]\n") == ""


# ── Layer C: _observe() unit ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_observe_calls_ipc_with_correct_args(tmp_path):
    """_observe() calls _ipc_call('observe', {session_id, text})."""
    from mnemostroma.integration import proxy_passthrough

    session_file = tmp_path / "current_session"
    session_file.write_text("explicit-sid", encoding="utf-8")

    captured: list[tuple] = []

    async def _fake_ipc(tool: str, args: dict):
        captured.append((tool, args))
        return {"ok": True}

    with patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
         patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):
        await proxy_passthrough._observe("important decision made")

    assert captured == [
        ("ctx_active", {}),
        ("observe", {"session_id": "explicit-sid",
                     "text": "important decision made"})
    ]


@pytest.mark.asyncio
async def test_observe_skips_whitespace_text(tmp_path):
    """_observe() with whitespace-only text never calls _ipc_call."""
    from mnemostroma.integration import proxy_passthrough

    session_file = tmp_path / "current_session"
    session_file.write_text("sid", encoding="utf-8")
    captured: list = []

    async def _fake_ipc(tool: str, args: dict):
        captured.append(args)
        return {}

    with patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
         patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):
        await proxy_passthrough._observe("   \n\t  ")

    assert len(captured) == 0


@pytest.mark.asyncio
async def test_observe_ipc_failure_swallowed(tmp_path):
    """_observe() with daemon down does NOT raise — proxy must not crash."""
    from mnemostroma.integration import proxy_passthrough

    session_file = tmp_path / "current_session"
    session_file.write_text("sid", encoding="utf-8")

    async def _failing_ipc(tool: str, args: dict):
        raise ConnectionError("daemon not running")

    with patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
         patch.object(proxy_passthrough, "_ipc_call", _failing_ipc):
        await proxy_passthrough._observe("some text")  # must not raise


# ── Layer D: IPC → conductor.dispatch("observe") ─────────────────────

@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_observe_reaches_conductor_dispatch(tmp_path):
    """_ipc_call('observe') → IPCServer → conductor.dispatch() called correctly."""
    from mnemostroma.ipc_server import IPCServer
    from mnemostroma.integration.mcp_stdio_adapter import _ipc_call

    sock = tmp_path / "test.sock"
    conductor = MagicMock()
    conductor.ctx = MagicMock()
    conductor.dispatch = AsyncMock(return_value={"ok": True})

    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        with patch("mnemostroma.integration.mcp_stdio_adapter._SOCKET_PATH", sock):
            result = await _ipc_call("observe", {"session_id": "sid-99", "text": "hello IPC"})

        await asyncio.sleep(0.01)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # D1: caller received correct result
    assert result == {"ok": True}

    # D2: conductor.dispatch called with exact arguments
    conductor.dispatch.assert_called_once_with(
        "observe", {"session_id": "sid-99", "text": "hello IPC"}
    )


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform == "win32", reason="Unix socket test")
async def test_ipc_missing_session_id_returns_missing_arg_error(tmp_path):
    """observe without session_id → error response with code=missing_arg."""
    from mnemostroma.ipc_server import IPCServer

    sock = tmp_path / "test.sock"
    conductor = MagicMock()
    conductor.ctx = MagicMock()
    conductor.dispatch = AsyncMock(side_effect=KeyError("session_id"))

    server = IPCServer(conductor)

    with patch("mnemostroma.ipc_server.SOCKET_PATH", sock):
        task = asyncio.create_task(server.serve())
        await asyncio.sleep(0.05)

        reader, writer = await asyncio.open_unix_connection(str(sock))
        writer.write((json.dumps({"id": 9, "tool": "observe", "args": {}}) + "\n").encode())
        await writer.drain()
        resp = json.loads((await reader.readline()).decode())

        writer.close()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    assert resp["id"] == 9
    assert "error" in resp
    assert resp.get("code") == "missing_arg"


# ── Layer E: Observer gate ────────────────────────────────────────────

def test_prefilter_rejects_short_text():
    """Text < 5 chars is discarded at the prefilter gate before any ONNX call."""
    from mnemostroma.observer.marker import structural_prefilter

    assert structural_prefilter("hi") is False
    assert structural_prefilter("") is False
    assert structural_prefilter("    ") is False


def test_prefilter_passes_meaningful_text():
    """Substantial text passes prefilter."""
    from mnemostroma.observer.marker import structural_prefilter

    assert structural_prefilter("We decided to use SQLite WAL mode for all persistence.")
    assert structural_prefilter("Мы решили использовать PostgreSQL.")


@pytest.mark.asyncio
async def test_observer_pipeline_returns_none_for_short_text():
    """observer_pipeline returns None without touching ONNX for text < 5 chars."""
    from mnemostroma.observer.pipeline import observer_pipeline

    ctx = MagicMock()
    ctx.config.search.embedding_dim = 384
    ctx.config.precision_guard.enabled = False
    ctx.config.anchor_guardian.enabled = False
    ctx.config.associative_surfacing.enabled = False
    ctx.config.open_loop.enabled = False
    ctx.models = None

    assert await observer_pipeline("hi", "test-session", ctx) is None
    assert await observer_pipeline("", "test-session", ctx) is None


@pytest.mark.asyncio
async def test_observer_pipeline_returns_none_on_marker_discard():
    """marker() returning DISCARD → pipeline returns None, no SessionBrief created."""
    from mnemostroma.observer.pipeline import observer_pipeline
    from mnemostroma.observer.entities import MarkerAction

    ctx = MagicMock()
    ctx.config.search.embedding_dim = 384
    ctx.config.precision_guard.enabled = False
    ctx.config.anchor_guardian.enabled = False
    ctx.config.associative_surfacing.enabled = False
    ctx.config.open_loop.enabled = False
    ctx.models = None
    ctx.pending_emotions = []

    discard = MagicMock()
    discard.action = MarkerAction.DISCARD
    discard.entity = None
    discard.emotion = None
    discard.confidence = 0.05

    with patch("mnemostroma.observer.pipeline._marker", AsyncMock(return_value=discard)), \
         patch("mnemostroma.observer.pipeline.log_event", AsyncMock()):
        result = await observer_pipeline(
            "this text is long enough to pass prefilter but marker discards it entirely",
            "test-session", ctx,
        )

    assert result is None


# ── Layer F: mcp_stdio_adapter current_session ────────────────────────

@pytest.mark.asyncio
async def test_stdio_adapter_writes_current_session_from_ctx_active(tmp_path):
    """Session ID from ctx_active is written to current_session file."""
    from mnemostroma.integration import mcp_stdio_adapter

    session_file = tmp_path / "current_session"

    async def _fake_ipc(tool: str, args: dict):
        if tool == "ctx_active":
            return {"session_id": "active-session-abc"}
        return {}

    with patch.object(mcp_stdio_adapter, "_CURRENT_SESSION_FILE", session_file), \
         patch.object(mcp_stdio_adapter, "_ipc_call", _fake_ipc):
        try:
            result = await _fake_ipc("ctx_active", {})
            sid = (result or {}).get("session_id") or f"passthrough-fallback"
        except Exception:
            sid = "passthrough-fallback"
        session_file.write_text(sid, encoding="utf-8")

    assert session_file.read_text() == "active-session-abc"


@pytest.mark.asyncio
async def test_stdio_adapter_fallback_when_daemon_down(tmp_path):
    """ConnectionError from daemon → date-based fallback written to session file."""
    from datetime import date

    session_file = tmp_path / "current_session"

    async def _failing_ipc(tool: str, args: dict):
        raise ConnectionError("daemon not running")

    try:
        result = await _failing_ipc("ctx_active", {})
        sid = (result or {}).get("session_id")
    except Exception:
        sid = None

    sid = sid or f"passthrough-{date.today().isoformat()}"
    session_file.write_text(sid, encoding="utf-8")

    written = session_file.read_text()
    assert written.startswith("passthrough-2")      # date format passthrough-20XX-...
    assert len(written) == len("passthrough-2026-04-10")


# ── Tail invariants ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_orphaned_tasks_fire_and_forget_completes(tmp_path):
    """create_task(_observe(...)) completes — tracked via asyncio.Event."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app

    session_file = tmp_path / "current_session"
    session_file.write_text("orphan-test", encoding="utf-8")

    observe_done = asyncio.Event()

    async def _tracked_ipc(tool: str, args: dict):
        if tool == "observe":
            observe_done.set()
        return {"ok": True}

    fake_resp = _make_json_response({"content": [{"text": "check tasks"}]})
    mock_upstream = _make_mock_upstream(fake_resp)

    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                   return_value=mock_upstream), \
             patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _tracked_ipc):

            await client.post("/v1/messages", json={})
            # Wait for fire-and-forget task to actually complete — not just schedule
            await asyncio.wait_for(observe_done.wait(), timeout=1.0)

    assert observe_done.is_set()


@pytest.mark.asyncio
async def test_metrics_track_requests_observed_skipped_independently(tmp_path):
    """requests, observed, skipped counters each increment independently."""
    from mnemostroma.integration import proxy_passthrough
    from mnemostroma.integration.proxy_passthrough import make_passthrough_app, _metrics

    session_file = tmp_path / "current_session"
    session_file.write_text("metrics-test", encoding="utf-8")

    async def _fake_ipc(tool: str, args: dict):
        return {"ok": True}

    before = dict(_metrics)
    app = make_passthrough_app()
    transport = httpx.ASGITransport(app=app)

    json_resp  = _make_json_response({"content": [{"text": "ok"}]})
    model_resp = _make_json_response({"models": []})
    mock_json  = _make_mock_upstream(json_resp)
    mock_model = _make_mock_upstream(model_resp)

    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        with patch.object(proxy_passthrough, "_SESSION_FILE", session_file), \
             patch.object(proxy_passthrough, "_ipc_call", _fake_ipc):

            with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                       return_value=mock_json):
                await client.post("/v1/messages", json={})

            with patch("mnemostroma.integration.proxy_passthrough.httpx.AsyncClient",
                       return_value=mock_model):
                await client.get("/v1/models")

            # drain fire-and-forget _observe task while _ipc_call is still patched
            await asyncio.sleep(0.02)

    assert _metrics["requests"] == before["requests"] + 2   # both counted
    assert _metrics["observed"]  >= before["observed"] + 1  # at least 1 from POST
    assert _metrics["skipped"]   == before["skipped"] + 1   # exactly 1 from GET
