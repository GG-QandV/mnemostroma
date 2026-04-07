# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for persistence invariant: RAM ⊆ DISK.

Covers:
- QueueFull: metrics["dropped_sessions"] incremented, ERROR logged (not warning)
- experience upsert guaranteed in SQLite after observe() hot path (no fire-and-forget)
- flush() drains all pending session writes before returning
"""
import asyncio
import json
import logging
import pytest
import aiosqlite
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch


# ── QueueFull behaviour ───────────────────────────────────────────────────────

def _make_db_manager(maxsize: int = 1):
    """Minimal DatabaseManager with tiny queue for QueueFull testing."""
    from mnemostroma.storage.sqlite import DatabaseManager
    db = AsyncMock()
    cfg_mock = MagicMock()
    cfg_mock.storage.batch_flush_size = 50
    cfg_mock.storage.async_flush_interval_sec = 5
    mgr = DatabaseManager(db, MagicMock(storage=cfg_mock.storage))
    mgr.queue = asyncio.Queue(maxsize=maxsize)
    ctx = MagicMock()
    ctx.metrics = {}
    mgr.ctx = ctx
    return mgr, ctx


def test_queue_full_increments_metric():
    """QueueFull must increment ctx.metrics['dropped_sessions']."""
    mgr, ctx = _make_db_manager(maxsize=1)

    session_a = MagicMock(session_id="s_a")
    session_b = MagicMock(session_id="s_b")

    mgr.queue_write(session_a)   # fills the queue (maxsize=1)
    mgr.queue_write(session_b)   # overflow

    assert ctx.metrics.get("dropped_sessions", 0) == 1


def test_queue_full_multiple_drops_accumulate():
    """Each additional QueueFull increments the counter."""
    mgr, ctx = _make_db_manager(maxsize=1)

    mgr.queue_write(MagicMock(session_id="s0"))  # fills
    mgr.queue_write(MagicMock(session_id="s1"))  # drop 1
    mgr.queue_write(MagicMock(session_id="s2"))  # drop 2

    assert ctx.metrics["dropped_sessions"] == 2


def test_queue_full_logs_error(caplog):
    """QueueFull must log at ERROR level, not WARNING."""
    mgr, ctx = _make_db_manager(maxsize=1)
    mgr.queue_write(MagicMock(session_id="fill"))

    with caplog.at_level(logging.ERROR, logger="mnemostroma.storage"):
        mgr.queue_write(MagicMock(session_id="overflow"))

    assert any("NOT persisted" in r.message or "violated" in r.message
               for r in caplog.records if r.levelno == logging.ERROR)


def test_queue_write_no_drop_on_space():
    """No drop metric when queue has space."""
    mgr, ctx = _make_db_manager(maxsize=10)
    for i in range(5):
        mgr.queue_write(MagicMock(session_id=f"s{i}"))
    assert ctx.metrics.get("dropped_sessions", 0) == 0


# ── experience guaranteed write ───────────────────────────────────────────────

@pytest_asyncio.fixture
async def mem_db():
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("""
        CREATE TABLE experience_metrics (
            tag TEXT PRIMARY KEY,
            session_count INTEGER NOT NULL DEFAULT 0,
            score_sum REAL NOT NULL DEFAULT 0.0,
            conflict_count INTEGER NOT NULL DEFAULT 0,
            last_updated INTEGER NOT NULL,
            emotion_positive INTEGER NOT NULL DEFAULT 0,
            emotion_negative INTEGER NOT NULL DEFAULT 0,
            emotion_intensity_sum REAL NOT NULL DEFAULT 0.0
        )
    """)
    await conn.commit()
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def db_manager(mem_db):
    from mnemostroma.storage.sqlite import DatabaseManager
    cfg = MagicMock()
    cfg.storage.batch_flush_size = 50
    cfg.storage.async_flush_interval_sec = 5
    mgr = DatabaseManager(mem_db, MagicMock(storage=cfg.storage))
    mgr.db = mem_db
    return mgr


@pytest.mark.asyncio
async def test_upsert_experience_immediately_in_db(db_manager):
    """upsert_experience() must be readable from SQLite right after await — no fire-and-forget."""
    await db_manager.upsert_experience(
        tag="python", session_count=3, score_sum=1.5,
        conflict_count=0, last_updated=9000,
        emotion_positive=2, emotion_negative=0, emotion_intensity_sum=1.0,
    )

    async with db_manager.db.execute(
        "SELECT session_count, emotion_positive FROM experience_metrics WHERE tag = ?",
        ("python",)
    ) as cur:
        row = await cur.fetchone()

    assert row is not None, "experience_metrics row missing after upsert"
    assert row[0] == 3
    assert row[1] == 2


@pytest.mark.asyncio
async def test_upsert_experience_no_pending_tasks(db_manager):
    """After await upsert_experience() there must be no pending asyncio tasks for this write."""
    before = len([t for t in asyncio.all_tasks() if "upsert" in t.get_name()])

    await db_manager.upsert_experience(
        tag="test", session_count=1, score_sum=0.5,
        conflict_count=0, last_updated=1000,
    )

    after = len([t for t in asyncio.all_tasks() if "upsert" in t.get_name()])
    assert after == before, "upsert_experience left a dangling asyncio task"


# ── flush drains queue ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_drains_all_pending(db_manager):
    """flush() must leave queue empty (size=0) after draining."""
    sessions = [MagicMock(session_id=f"s{i}") for i in range(5)]
    for s in sessions:
        db_manager.queue.put_nowait(s)

    assert db_manager.queue.qsize() == 5

    # _flush_batch needs to handle MagicMock sessions gracefully
    with patch.object(db_manager, "_flush_batch", new=AsyncMock()):
        await db_manager.flush()

    assert db_manager.queue.qsize() == 0


@pytest.mark.asyncio
async def test_flush_empty_queue_is_noop(db_manager):
    """flush() on empty queue must not raise and queue stays empty."""
    assert db_manager.queue.qsize() == 0
    await db_manager.flush()
    assert db_manager.queue.qsize() == 0
