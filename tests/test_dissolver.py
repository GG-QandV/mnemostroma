# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Dissolver eviction correctness — matrix rebuild, mapping cleanup, flush guarantee, §5.3."""
import time
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from mnemostroma.memory.dissolver import Dissolver, _eviction_priority, can_evict, _rebuild_session_index
from mnemostroma.memory.hnsw import MatrixSearch
from mnemostroma.memory.session_index import SessionBrief


def _make_sb(session_id, importance="important", intensity=0.0, age_days=0, conflict=False,
             deadline_ts=None, embedding=None):
    sb = SessionBrief(
        session_id=session_id,
        brief=f"brief-{session_id}",
        tags=["test"],
        importance=importance,
        score=0.5,
        resolution=1.0,
        created_at=int(time.time()) - int(age_days * 86400),
    )
    sb.intensity = intensity
    if conflict:
        sb.conflict_flag = True
    if deadline_ts is not None:
        sb.deadline_ts = deadline_ts
        sb.urgency_expired = False
    return sb


class _MockCtx:
    def __init__(self, dim=4):
        self.ram_index = {}
        self.sid_to_id = {}
        self.id_to_sid = {}
        self._next_session_label = 0
        self.session_index = MatrixSearch(dim=dim)
        self.persistence = None
        self.db = None
        self.log_writer = None
        self.config = MagicMock()
        self.config.logging.enabled = False
        self.config.resources.session_window_size = 100
        self.config.resources.dissolution_interval_sec = 60.0
        self.metrics = {}

    def get_session_label(self, session_id: str) -> int:
        if session_id not in self.sid_to_id:
            label = self._next_session_label
            self._next_session_label += 1
            self.sid_to_id[session_id] = label
            self.id_to_sid[label] = session_id
        return self.sid_to_id[session_id]


def _add_session(ctx, sb, embedding=None):
    ctx.ram_index[sb.session_id] = sb
    if embedding is not None:
        sb.embedding = embedding
        label = ctx.get_session_label(sb.session_id)
        ctx.session_index.add_items([embedding], [label])


# ── MatrixSearch.clear() ─────────────────────────────────────────────────────

def test_matrix_search_clear():
    ms = MatrixSearch(dim=4)
    ms.add_items([np.array([1, 0, 0, 0], dtype='float32')], [0])
    assert ms.get_current_count() == 1
    ms.clear()
    assert ms.get_current_count() == 0
    assert len(ms._labels) == 0
    assert ms._vectors.shape == (0, 4)


# ── evict_n_oldest: mapping cleanup ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_evict_cleans_sid_to_id():
    ctx = _MockCtx()
    sb = _make_sb("s0")
    _add_session(ctx, sb)
    dissolver = Dissolver(ctx)
    await dissolver.evict_n_oldest(1)
    assert "s0" not in ctx.sid_to_id


@pytest.mark.asyncio
async def test_evict_cleans_id_to_sid():
    ctx = _MockCtx()
    sb = _make_sb("s0")
    _add_session(ctx, sb)
    label = ctx.get_session_label("s0")
    dissolver = Dissolver(ctx)
    await dissolver.evict_n_oldest(1)
    assert label not in ctx.id_to_sid


@pytest.mark.asyncio
async def test_evict_removes_from_ram_index():
    ctx = _MockCtx()
    for i in range(5):
        _add_session(ctx, _make_sb(f"s{i}"))
    dissolver = Dissolver(ctx)
    await dissolver.evict_n_oldest(3)
    assert len(ctx.ram_index) == 2


# ── _rebuild_session_index ────────────────────────────────────────────────────

def test_rebuild_removes_evicted_vectors():
    ctx = _MockCtx(dim=4)
    emb = np.array([1, 0, 0, 0], dtype='float32')
    sb0 = _make_sb("s0", embedding=emb)
    sb1 = _make_sb("s1", embedding=emb)
    _add_session(ctx, sb0, emb)
    _add_session(ctx, sb1, emb)

    # Manually evict s0 from ram_index (simulate evict step)
    del ctx.ram_index["s0"]
    label0 = ctx.sid_to_id.pop("s0", None)
    if label0 is not None:
        ctx.id_to_sid.pop(label0, None)

    _rebuild_session_index(ctx)

    # Matrix should only have s1 — and every returned label maps to a live session
    assert ctx.session_index.get_current_count() == 1
    labels, _ = ctx.session_index.knn_query(emb, k=5)
    for lab in labels:
        sid = ctx.id_to_sid.get(lab)
        assert sid is not None, f"label {lab} maps to nothing after rebuild"
        assert sid in ctx.ram_index, f"label {lab} → '{sid}' not in ram_index"


@pytest.mark.asyncio
async def test_evict_rebuild_knn_no_dead_labels():
    ctx = _MockCtx(dim=4)
    emb = np.array([1, 0, 0, 0], dtype='float32')
    for i in range(4):
        _add_session(ctx, _make_sb(f"s{i}"), emb)

    # Save labels of all sessions before eviction
    all_labels_before = set(ctx.id_to_sid.keys())

    dissolver = Dissolver(ctx)
    await dissolver.evict_n_oldest(2)

    # knn should not return labels of evicted sessions
    labels, _ = ctx.session_index.knn_query(emb, k=10)
    for lab in labels:
        assert lab in ctx.id_to_sid, f"label {lab} is dead but returned by knn"


# ── can_evict ─────────────────────────────────────────────────────────────────

def test_can_evict_principle_false():
    sb = _make_sb("p", importance="principle")
    assert can_evict(sb, MagicMock()) is False


def test_can_evict_live_deadline_false():
    sb = _make_sb("d", importance="important")
    sb.deadline_ts = int(time.time()) + 3600
    sb.urgency_expired = False
    assert can_evict(sb, MagicMock()) is False


def test_can_evict_conflict_flag_false():
    sb = _make_sb("c", conflict=True)
    assert can_evict(sb, MagicMock()) is False


def test_can_evict_normal_true():
    sb = _make_sb("n", importance="important")
    assert can_evict(sb, MagicMock()) is True


# ── §5.3: high intensity not evicted first ───────────────────────────────────

def test_high_intensity_not_evicted_first():
    """§5.3: session with high intensity has higher priority → NOT evicted first."""
    low_int  = _make_sb("low",  importance="important", intensity=0.0, age_days=1)
    high_int = _make_sb("high", importance="important", intensity=0.9, age_days=1)

    p_low  = _eviction_priority(low_int)
    p_high = _eviction_priority(high_int)

    # Lower _eviction_priority value → evicted first
    # high intensity should have HIGHER priority → NOT first
    assert p_high > p_low, (
        f"high_intensity priority ({p_high:.4f}) should exceed low_intensity ({p_low:.4f})"
    )


# ── P1: flush before eviction ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flush_called_before_eviction():
    ctx = _MockCtx()
    _add_session(ctx, _make_sb("s0"))
    flush_mock = AsyncMock()
    persistence_mock = MagicMock()
    persistence_mock.flush = flush_mock
    ctx.persistence = persistence_mock

    dissolver = Dissolver(ctx)
    await dissolver.evict_n_oldest(1)

    flush_mock.assert_called_once()
