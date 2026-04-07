# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for B.2 continuation detector — 11 cases per spec."""
import time
import numpy as np
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from mnemostroma.core import Config, SystemContext
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.observer.continuation_detector import (
    detect_continuation, _tag_overlap, _recency_score, _chain_depth,
)


@pytest.fixture
def config():
    return Config.load(Path(__file__).parent.parent / "config.json")


def _make_sb(sid, tags=None, created_at=None, score=0.5):
    return SessionBrief(
        session_id=sid, brief=f"brief {sid}",
        tags=tags or [], importance="important",
        score=score, resolution=1.0,
        created_at=created_at or int(time.time()),
    )


def _make_ctx(config, sessions: dict, hnsw_labels: dict = None):
    """Build a minimal ctx with mocked HNSW."""
    ctx = SystemContext(config=config)
    ctx.ram_index = sessions
    ctx.anchor_index = None

    # sid_to_id / id_to_sid
    hnsw_labels = hnsw_labels or {sid: i for i, sid in enumerate(sessions)}
    ctx.sid_to_id = hnsw_labels
    ctx.id_to_sid = {v: k for k, v in hnsw_labels.items()}

    return ctx


def _mock_hnsw(labels_distances: list):
    """Return a mock HNSW that yields (labels, distances) from a list of (label, dist) pairs."""
    hnsw = MagicMock()
    hnsw.get_current_count.return_value = len(labels_distances)
    lbls = [ld[0] for ld in labels_distances]
    dsts = [ld[1] for ld in labels_distances]
    hnsw.knn_query.return_value = (lbls, dsts)
    return hnsw


# ── 1. empty index → new ──────────────────────────────────────
def test_empty_index_returns_new(config):
    ctx = _make_ctx(config, {})
    ctx.session_index = MagicMock()
    ctx.session_index.get_current_count.return_value = 0

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, ["tag1"], ctx)
    assert result["state"] == "new"
    assert result["continuation_of"] is None


# ── 2. high similarity → continuation ────────────────────────
def test_high_similarity_continuation(config):
    sb = _make_sb("s1", tags=["python", "memory"])
    ctx = _make_ctx(config, {"s1": sb})
    # cosine distance 0.05 → similarity 0.95, tags overlap 1.0, recency ~1.0
    # combined ≈ 0.7×0.95 + 0.1×1.0 + 0.2×1.0 = 0.665 + 0.1 + 0.2 = 0.965
    ctx.session_index = _mock_hnsw([(0, 0.05)])

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, ["python", "memory"], ctx,
                                 continuation_score_threshold=0.65)
    assert result["state"] == "continuation"
    assert result["continuation_of"] == "s1"
    assert result["best_score"] >= 0.65


# ── 3. medium similarity → related ───────────────────────────
def test_medium_similarity_related(config):
    sb = _make_sb("s1", tags=["other"])
    ctx = _make_ctx(config, {"s1": sb})
    # cosine distance 0.45 → similarity 0.55 (below continuation threshold 0.65 combined)
    # combined ≈ 0.7×0.55 + 0.1×0 + 0.2×1.0 = 0.385 + 0 + 0.2 = 0.585 < 0.65
    # but cosine 0.55 ≥ related_cosine_threshold 0.45
    ctx.session_index = _mock_hnsw([(0, 0.45)])

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, ["new_tag"], ctx,
                                 continuation_score_threshold=0.65,
                                 related_cosine_threshold=0.45)
    assert result["state"] == "related"
    assert result["continuation_of"] == "s1"
    assert result["continuation_depth"] == 0  # related doesn't add depth


# ── 4. low similarity → new ───────────────────────────────────
def test_low_similarity_new(config):
    sb = _make_sb("s1", tags=[])
    ctx = _make_ctx(config, {"s1": sb})
    # cosine distance 0.8 → similarity 0.2, no tags → combined ≈ 0.14+0+0.2=0.34
    ctx.session_index = _mock_hnsw([(0, 0.8)])

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, [], ctx)
    assert result["state"] == "new"


# ── 5. age filter excludes old sessions ───────────────────────
def test_age_filter_excludes_old(config):
    old_ts = int(time.time()) - 10 * 86400  # 10 days ago
    sb = _make_sb("s_old", created_at=old_ts)
    ctx = _make_ctx(config, {"s_old": sb})
    ctx.session_index = _mock_hnsw([(0, 0.05)])  # would be continuation if not old

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, [], ctx, max_age_days=7)
    assert result["state"] == "new"
    assert result["candidates_count"] == 0


# ── 6. tag overlap boosts score ───────────────────────────────
def test_tag_overlap_boosts_score(config):
    sb_no_tags  = _make_sb("s_none",  tags=[])
    sb_full_tags = _make_sb("s_full", tags=["a", "b", "c"])
    ctx = _make_ctx(config, {"s_none": sb_no_tags, "s_full": sb_full_tags},
                   hnsw_labels={"s_none": 0, "s_full": 1})
    # Both at same cosine distance
    ctx.session_index = _mock_hnsw([(0, 0.3), (1, 0.3)])

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, ["a", "b", "c"], ctx)
    # s_full should win due to tag overlap
    assert result["continuation_of"] == "s_full"


# ── 7. best candidate wins ────────────────────────────────────
def test_best_candidate_wins(config):
    sb1 = _make_sb("s1", tags=[])
    sb2 = _make_sb("s2", tags=[])
    ctx = _make_ctx(config, {"s1": sb1, "s2": sb2},
                   hnsw_labels={"s1": 0, "s2": 1})
    # s2 has better cosine distance
    ctx.session_index = _mock_hnsw([(0, 0.5), (1, 0.2)])

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, [], ctx)
    assert result["continuation_of"] == "s2"


# ── 8. chain depth tracing ────────────────────────────────────
def test_chain_depth_tracing(config):
    from mnemostroma.subconscious.anchor_index import AnchorIndex
    from mnemostroma.subconscious.anchor import Anchor

    now = int(time.time())
    sb1 = _make_sb("s1")
    sb2 = _make_sb("s2")
    ctx = _make_ctx(config, {"s1": sb1, "s2": sb2},
                   hnsw_labels={"s1": 0, "s2": 1})

    # Build anchor chain: s2 → continuation of s1
    ai = AnchorIndex(max_capacity=100)
    a1 = Anchor(anchor_id="s1", session_id="s1", brief="b1",
                anchor_type="event", key_facts=[], flags={"continuation_of": None},
                decay_level=0, access_count=0,
                last_accessed_at=now, created_at=now, updated_at=now)
    a2 = Anchor(anchor_id="s2", session_id="s2", brief="b2",
                anchor_type="event", key_facts=[], flags={"continuation_of": "s1"},
                decay_level=0, access_count=0,
                last_accessed_at=now, created_at=now, updated_at=now)
    ai.put(a1); ai.put(a2)
    ctx.anchor_index = ai

    # high similarity with s2 → continuation, depth should be chain(s2)+1 = 2
    ctx.session_index = _mock_hnsw([(1, 0.05)])
    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, [], ctx, continuation_score_threshold=0.50)
    assert result["state"] == "continuation"
    assert result["continuation_of"] == "s2"
    assert result["continuation_depth"] == 2  # s2 is depth 1 in chain, +1 = 2


# ── 9. circular chain protection ─────────────────────────────
def test_circular_chain_protection(config):
    from mnemostroma.subconscious.anchor_index import AnchorIndex
    from mnemostroma.subconscious.anchor import Anchor

    now = int(time.time())
    sb1 = _make_sb("s1")
    ctx = _make_ctx(config, {"s1": sb1}, hnsw_labels={"s1": 0})

    ai = AnchorIndex(max_capacity=100)
    # s1 points to itself — circular
    a1 = Anchor(anchor_id="s1", session_id="s1", brief="b1",
                anchor_type="event", key_facts=[], flags={"continuation_of": "s1"},
                decay_level=0, access_count=0,
                last_accessed_at=now, created_at=now, updated_at=now)
    ai.put(a1)
    ctx.anchor_index = ai

    # Should not infinite-loop
    depth = _chain_depth("s1", ctx)
    assert depth == 0  # self-reference → 0


# ── 10. no hnsw → new ─────────────────────────────────────────
def test_no_hnsw_returns_new(config):
    ctx = _make_ctx(config, {})
    ctx.session_index = None

    vec = np.random.rand(384).astype(np.float32)
    result = detect_continuation(vec, [], ctx)
    assert result["state"] == "new"


# ── 11. recency score unit tests ──────────────────────────────
def test_recency_score():
    now = int(time.time())
    assert _recency_score(now, max_age_days=7) == pytest.approx(1.0, abs=0.05)
    assert _recency_score(now - 3 * 86400, max_age_days=7) == pytest.approx(1 - 3/7, abs=0.05)
    assert _recency_score(now - 8 * 86400, max_age_days=7) == 0.0


def test_tag_overlap():
    assert _tag_overlap(["a", "b"], ["a", "b"]) == pytest.approx(1.0)
    assert _tag_overlap(["a", "b"], ["c", "d"]) == pytest.approx(0.0)
    assert _tag_overlap(["a", "b"], ["b", "c"]) == pytest.approx(1/3, abs=0.01)
    assert _tag_overlap([], ["a"]) == pytest.approx(0.0)
