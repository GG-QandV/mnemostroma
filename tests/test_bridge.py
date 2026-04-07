# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Session Bridge: ctx_sync() and ctx_load()."""
import asyncio
import time
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from mnemostroma.core import SystemContext, Config
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.tools.bridge import ctx_sync, ctx_load


@pytest.fixture
def config():
    return Config.load(Path(__file__).parent.parent / "config.json")


@pytest.fixture
def make_sb():
    def _make(sid="s1", importance="important", score=0.5, embedding=None):
        return SessionBrief(
            session_id=sid,
            brief=f"brief of {sid}",
            tags=["tag1"],
            importance=importance,
            score=score,
            resolution=1.0,
            created_at=int(time.time()),
            embedding=embedding,
        )
    return _make


def _make_persistence_mock(sync_result=None, get_session=None):
    """Build a minimal PersistenceLayer mock."""
    m = MagicMock()
    m.sync = AsyncMock(return_value=sync_result or {"flushed_sessions": 0, "wal_pages": -1, "checkpoint_mode": "PASSIVE"})
    m.get_session_by_id = AsyncMock(return_value=get_session)
    return m


# ──────────────────────────────────────────────
# ctx_sync tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sync_no_persistence(config):
    """ctx_sync returns zero-stats when persistence is None."""
    ctx = SystemContext(config=config)
    ctx.persistence = None
    stats = await ctx_sync(ctx)
    assert stats["flushed_sessions"] == 0
    assert stats["wal_pages"] == -1


@pytest.mark.asyncio
async def test_sync_delegates_to_persistence(config):
    """ctx_sync delegates to ctx.persistence.sync() and returns its result."""
    ctx = SystemContext(config=config)
    expected = {"flushed_sessions": 3, "wal_pages": 5, "checkpoint_mode": "PASSIVE"}
    ctx.persistence = _make_persistence_mock(sync_result=expected)

    stats = await ctx_sync(ctx)
    assert stats == expected
    ctx.persistence.sync.assert_called_once_with(checkpoint_mode="PASSIVE")


@pytest.mark.asyncio
async def test_sync_passes_checkpoint_mode(config):
    """ctx_sync passes checkpoint_mode through to persistence.sync()."""
    ctx = SystemContext(config=config)
    ctx.persistence = _make_persistence_mock(
        sync_result={"flushed_sessions": 0, "wal_pages": 0, "checkpoint_mode": "TRUNCATE"}
    )

    await ctx_sync(ctx, checkpoint_mode="TRUNCATE")
    ctx.persistence.sync.assert_called_once_with(checkpoint_mode="TRUNCATE")


# ──────────────────────────────────────────────
# ctx_load tests
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_load_ram_hit(config, make_sb):
    """ctx_load returns immediately if session is already in RAM."""
    ctx = SystemContext(config=config)
    sb = make_sb("already_hot")
    ctx.ram_index["already_hot"] = sb

    result = await ctx_load("already_hot", ctx)
    assert result is sb


@pytest.mark.asyncio
async def test_load_no_persistence(config):
    """ctx_load returns None when persistence is absent."""
    ctx = SystemContext(config=config)
    ctx.persistence = None
    result = await ctx_load("missing", ctx)
    assert result is None


@pytest.mark.asyncio
async def test_load_not_found_in_sqlite(config, mocker):
    """ctx_load returns None when session not in SQLite."""
    ctx = SystemContext(config=config)
    ctx.persistence = _make_persistence_mock(get_session=None)

    result = await ctx_load("ghost_session", ctx)
    assert result is None


@pytest.mark.asyncio
async def test_load_cold_load_no_embedding(config, make_sb, mocker):
    """ctx_load adds session to ram_index even without embedding."""
    ctx = SystemContext(config=config)
    sb = make_sb("cold_no_embed", embedding=None)
    ctx.persistence = _make_persistence_mock(get_session=sb)
    ctx.session_index = None  # no HNSW

    result = await ctx_load("cold_no_embed", ctx)
    assert result is sb
    assert ctx.ram_index["cold_no_embed"] is sb


@pytest.mark.asyncio
async def test_load_cold_load_with_embedding(config, make_sb, mocker):
    """ctx_load inserts embedding into HNSW when present."""
    ctx = SystemContext(config=config)
    vec = np.random.rand(384).astype(np.float16)
    sb = make_sb("cold_embed", embedding=vec)
    ctx.persistence = _make_persistence_mock(get_session=sb)

    # Minimal HNSW mock
    hnsw_mock = MagicMock()
    hnsw_mock.get_current_count.return_value = 0
    hnsw_mock.get_max_elements.return_value = 1000
    ctx.session_index = hnsw_mock

    result = await ctx_load("cold_embed", ctx)
    assert result is sb
    hnsw_mock.add_items.assert_called_once()
    assert ctx.ram_index["cold_embed"] is sb


@pytest.mark.asyncio
async def test_load_evicts_lowest_score(config, make_sb, mocker):
    """ctx_load evicts lowest-score session when RAM window is full."""
    ctx = SystemContext(config=config)
    window = ctx.config.resources.session_window_size

    # Fill RAM to capacity
    for i in range(window):
        ctx.ram_index[f"s{i}"] = make_sb(f"s{i}", score=float(i + 1))

    # The lowest-score session is s0 (score=1.0)
    low_score_sid = "s0"

    new_sb = make_sb("new_session", embedding=None)
    ctx.persistence = _make_persistence_mock(get_session=new_sb)
    ctx.session_index = None
    ctx.anchor_index = None

    await ctx_load("new_session", ctx)

    assert low_score_sid not in ctx.ram_index
    assert "new_session" in ctx.ram_index


@pytest.mark.asyncio
async def test_load_idempotent(config, make_sb):
    """Calling ctx_load twice returns the same object without duplicate SQLite calls."""
    ctx = SystemContext(config=config)
    sb = make_sb("idem")
    ctx.persistence = _make_persistence_mock(get_session=sb)
    ctx.session_index = None

    r1 = await ctx_load("idem", ctx)
    # Second call: already in RAM
    r2 = await ctx_load("idem", ctx)
    assert r1 is r2
    # persistence called only once (first load)
    ctx.persistence.get_session_by_id.assert_called_once()


# ──────────────────────────────────────────────
# SystemContext method wiring
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_sync_method(config):
    """ctx.sync() delegates to ctx_sync()."""
    ctx = SystemContext(config=config)
    ctx.persistence = None
    stats = await ctx.sync()
    assert "flushed_sessions" in stats


@pytest.mark.asyncio
async def test_ctx_load_method(config, make_sb):
    """ctx.load() delegates to ctx_load()."""
    ctx = SystemContext(config=config)
    sb = make_sb("via_method")
    ctx.ram_index["via_method"] = sb
    result = await ctx.load("via_method")
    assert result is sb
