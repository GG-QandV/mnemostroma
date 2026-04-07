# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for daemon infrastructure: DBManager.flush(), PulseWriter, StatusWriter, sdk.py."""
import asyncio
import json
import time
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch

import pytest
import aiosqlite

from mnemostroma.memory.daemon_metrics import PulseWriter, StatusWriter
from mnemostroma.memory.session_index import SessionBrief


# ── Shared mock context ───────────────────────────────────────────────────────

def _make_ctx(tmp_dir: Path = None):
    ctx = MagicMock()
    ctx.ram_index = {}
    ctx.urgency_index = {}
    ctx.metrics = {}
    ctx.config.resources.ram_budget_mb = 631.0
    ctx.session_index.get_current_count.return_value = 0
    ctx.content_index.get_current_count.return_value = 0
    ctx.persistence.pending_writes.return_value = 0
    return ctx


# ── DBManager.flush() ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_drains_queue():
    """flush() consumes all pending items and calls _flush_batch."""
    from mnemostroma.storage.sqlite import DatabaseManager

    db = await aiosqlite.connect(":memory:")
    cfg = MagicMock()
    cfg.storage.async_flush_interval_sec = 5.0
    cfg.storage.batch_flush_size = 100

    dm = DatabaseManager(db, cfg)

    flushed_batches = []
    async def fake_flush_batch(batch):
        flushed_batches.append(list(batch))
    dm._flush_batch = fake_flush_batch

    # Put 3 items into queue without starting the worker
    for i in range(3):
        sb = MagicMock()
        sb.session_id = f"s{i}"
        dm.queue.put_nowait(sb)

    await dm.flush()

    assert len(flushed_batches) == 1
    assert len(flushed_batches[0]) == 3
    assert dm.queue.empty()
    await db.close()


@pytest.mark.asyncio
async def test_flush_empty_queue_no_error():
    from mnemostroma.storage.sqlite import DatabaseManager
    db = await aiosqlite.connect(":memory:")
    cfg = MagicMock()
    cfg.storage.async_flush_interval_sec = 5.0
    cfg.storage.batch_flush_size = 100
    dm = DatabaseManager(db, cfg)
    await dm.flush()  # must not raise
    await db.close()


@pytest.mark.asyncio
async def test_flush_stops_at_sentinel():
    """flush() stops at None sentinel and returns it to the queue."""
    from mnemostroma.storage.sqlite import DatabaseManager
    db = await aiosqlite.connect(":memory:")
    cfg = MagicMock()
    cfg.storage.async_flush_interval_sec = 5.0
    cfg.storage.batch_flush_size = 100
    dm = DatabaseManager(db, cfg)

    sb = MagicMock(); sb.session_id = "s0"
    dm.queue.put_nowait(sb)
    dm.queue.put_nowait(None)   # sentinel
    dm.queue.put_nowait(MagicMock())  # item after sentinel — must NOT be consumed

    flushed = []
    async def fake_flush_batch(batch): flushed.extend(batch)
    dm._flush_batch = fake_flush_batch

    await dm.flush()

    assert len(flushed) == 1          # only sb, not the item after sentinel
    assert dm.queue.qsize() == 2      # None + item after sentinel back in queue
    await db.close()


# ── PulseWriter ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pulse_writer_writes_file(tmp_path):
    ctx = _make_ctx()
    ctx.ram_index = {"s0": MagicMock(), "s1": MagicMock()}
    ctx.urgency_index = {"u1": {"expired": False}}

    with patch("mnemostroma.memory.daemon_metrics.METRICS_DIR", tmp_path), \
         patch("mnemostroma.memory.daemon_metrics.PULSE_PATH", tmp_path / "pulse.json"):
        writer = PulseWriter(ctx, interval=0.05)
        await writer.start()
        await asyncio.sleep(0.15)
        await writer.stop()

    payload = json.loads((tmp_path / "pulse.json").read_text())
    assert payload["sessions"] == 2
    assert payload["urgency_active"] == 1
    assert "ram_mb" in payload
    assert "ts" in payload


@pytest.mark.asyncio
async def test_pulse_writer_stop_clean(tmp_path):
    ctx = _make_ctx()
    with patch("mnemostroma.memory.daemon_metrics.METRICS_DIR", tmp_path), \
         patch("mnemostroma.memory.daemon_metrics.PULSE_PATH", tmp_path / "pulse.json"):
        writer = PulseWriter(ctx, interval=60.0)  # long interval — stop before first write
        await writer.start()
        await writer.stop()
    # No error raised — clean stop even without a write cycle


# ── StatusWriter ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_status_writer_writes_file(tmp_path):
    ctx = _make_ctx()
    ctx.session_index.get_current_count.return_value = 5
    ctx.content_index.get_current_count.return_value = 3
    ctx.persistence.pending_writes.return_value = 2

    with patch("mnemostroma.memory.daemon_metrics.METRICS_DIR", tmp_path), \
         patch("mnemostroma.memory.daemon_metrics.STATUS_PATH", tmp_path / "status.json"):
        writer = StatusWriter(ctx, interval=0.05)
        await writer.start()
        await asyncio.sleep(0.15)
        await writer.stop()

    payload = json.loads((tmp_path / "status.json").read_text())
    assert payload["session_index_count"] == 5
    assert payload["content_index_count"] == 3
    assert payload["pending_writes"] == 2
    assert "ts" in payload


# ── sdk.build_memory_context ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_build_memory_context_returns_xml():
    from mnemostroma.integration.sdk import build_memory_context

    ctx = MagicMock()
    fake_block = MagicMock()
    fake_block.context = '<memory_context updated="now"><status>empty</status></memory_context>'

    mock_instance = MagicMock()
    mock_instance.inject = AsyncMock(return_value=fake_block)

    with patch("mnemostroma.integration.sdk.ConductorProxy", return_value=mock_instance):
        result = await build_memory_context("test query", ctx)

    assert result.startswith("<memory_context")
    mock_instance.inject.assert_called_once_with("test query", max_tokens=600, include_tools=False)


@pytest.mark.asyncio
async def test_build_memory_context_passes_max_tokens():
    from mnemostroma.integration.sdk import build_memory_context

    ctx = MagicMock()
    fake_block = MagicMock()
    fake_block.context = "<memory_context/>"

    mock_instance = MagicMock()
    mock_instance.inject = AsyncMock(return_value=fake_block)

    with patch("mnemostroma.integration.sdk.ConductorProxy", return_value=mock_instance):
        await build_memory_context("q", ctx, max_tokens=300)

    mock_instance.inject.assert_called_once_with("q", max_tokens=300, include_tools=False)
