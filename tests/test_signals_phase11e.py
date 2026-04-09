# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Phase 11.E — Open Loop Detector."""
import time
import pytest
import numpy as np
from unittest.mock import MagicMock

from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.subconscious.anchor_index import AnchorIndex
from mnemostroma.subconscious.guardian import _keyword_open_loop, scan_open_loops


def _make_anchor(anchor_id, brief, anchor_type="decision", outcome="pending", embedding=None):
    a = Anchor(
        anchor_id=anchor_id,
        session_id=anchor_id,
        brief=brief,
        anchor_type=anchor_type,
        created_at=int(time.time()),
        updated_at=int(time.time()),
    )
    a.flags["outcome"] = outcome
    a.embedding = embedding
    return a


class _MockCtx:
    def __init__(self):
        self.anchor_index = AnchorIndex(max_capacity=100)
        self.recently_looped = {}


# ── Layer 1: _keyword_open_loop ──────────────────────────────────────────────

def test_keyword_open_loop_matches_pending_decision():
    ctx = _MockCtx()
    ctx.anchor_index.put(_make_anchor("a1", "deploy production server", "decision", "pending"))
    hits = _keyword_open_loop("should we deploy production today?", ctx)
    assert len(hits) == 1
    assert hits[0]["anchor_id"] == "a1"


def test_keyword_open_loop_skips_resolved():
    ctx = _MockCtx()
    ctx.anchor_index.put(_make_anchor("a2", "deploy production server", "decision", "success"))
    hits = _keyword_open_loop("deploy production now", ctx)
    assert hits == []


def test_keyword_open_loop_skips_non_decision_types():
    ctx = _MockCtx()
    ctx.anchor_index.put(_make_anchor("a3", "deploy server milestone", "milestone", "pending"))
    hits = _keyword_open_loop("deploy server milestone", ctx)
    assert hits == []


def test_keyword_open_loop_skips_constraint():
    """constraint type is covered by Guardian, not Open Loop."""
    ctx = _MockCtx()
    ctx.anchor_index.put(_make_anchor("a4", "never delete production data", "constraint", "pending"))
    hits = _keyword_open_loop("delete production data?", ctx)
    assert hits == []


def test_keyword_open_loop_respects_cooldown():
    ctx = _MockCtx()
    ctx.anchor_index.put(_make_anchor("a5", "deploy service decision", "decision", "pending"))
    # First hit
    hits = _keyword_open_loop("deploy service", ctx)
    assert len(hits) == 1
    # Second hit — should be suppressed by cooldown
    hits2 = _keyword_open_loop("deploy service again", ctx)
    assert hits2 == []


def test_keyword_open_loop_skips_short_words():
    ctx = _MockCtx()
    # "run" is 3 chars < 4, "it" is 2 — won't match
    ctx.anchor_index.put(_make_anchor("a6", "run it now", "decision", "pending"))
    hits = _keyword_open_loop("run it now please", ctx)
    assert hits == []


def test_keyword_open_loop_no_anchor_index():
    ctx = MagicMock()
    del ctx.anchor_index  # simulate missing attr
    ctx = type("C", (), {})()
    hits = _keyword_open_loop("deploy production", ctx)
    assert hits == []


# ── Layer 2: scan_open_loops (async semantic) ────────────────────────────────

@pytest.mark.asyncio
async def test_scan_open_loops_fires_on_similar_pending():
    ctx = _MockCtx()
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    ctx.anchor_index.put(_make_anchor("b1", "launch product", "decision", "pending", embedding=vec))

    query = np.array([0.99, 0.1, 0.0], dtype=np.float32)
    query /= np.linalg.norm(query)
    hits = await scan_open_loops(query, ctx, threshold=0.7)
    assert len(hits) == 1
    assert hits[0]["anchor_id"] == "b1"


@pytest.mark.asyncio
async def test_scan_open_loops_skips_resolved():
    ctx = _MockCtx()
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    ctx.anchor_index.put(_make_anchor("b2", "launch product", "decision", "success", embedding=vec))

    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = await scan_open_loops(query, ctx, threshold=0.5)
    assert hits == []


@pytest.mark.asyncio
async def test_scan_open_loops_skips_no_embedding():
    ctx = _MockCtx()
    ctx.anchor_index.put(_make_anchor("b3", "launch product", "decision", "pending", embedding=None))
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = await scan_open_loops(query, ctx, threshold=0.5)
    assert hits == []


@pytest.mark.asyncio
async def test_scan_open_loops_respects_cooldown():
    ctx = _MockCtx()
    vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    ctx.anchor_index.put(_make_anchor("b4", "launch product", "decision", "pending", embedding=vec))
    ctx.recently_looped["b4"] = time.time()  # just warned

    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = await scan_open_loops(query, ctx, threshold=0.5, cooldown_sec=3600.0)
    assert hits == []


@pytest.mark.asyncio
async def test_scan_open_loops_max_results():
    ctx = _MockCtx()
    for i in range(10):
        vec = np.array([1.0, float(i) * 0.01, 0.0], dtype=np.float32)
        vec /= np.linalg.norm(vec)
        ctx.anchor_index.put(_make_anchor(f"c{i}", f"deploy cluster {i}", "decision", "pending", embedding=vec))
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = await scan_open_loops(query, ctx, threshold=0.5, max_results=3)
    assert len(hits) <= 3


@pytest.mark.asyncio
async def test_scan_open_loops_empty_index():
    ctx = _MockCtx()
    query = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    hits = await scan_open_loops(query, ctx, threshold=0.5)
    assert hits == []
