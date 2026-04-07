# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Phase 5: t_rel graph (5.1), pending_emotions (5.2), eviction v2 (5.4)."""
import time
import pytest
import numpy as np
from unittest.mock import MagicMock, AsyncMock

from mnemostroma.observer.entities import (
    Entity, EntityType, SourceType,
    Emotion, EmotionCharge,
    TemporalMarker, TemporalRelations,
    TimeRef, Explicitness,
    MarkerAction,
)
from mnemostroma.observer.marker import (
    marker, _build_t_rel, infer_temporal,
)
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.memory.dissolver import _eviction_priority, _IMPORTANCE_WEIGHT


# ---------------------------------------------------------------------------
# 5.1 — t_rel graph
# ---------------------------------------------------------------------------

def test_build_t_rel_inferred_past():
    """Inferred past after chain entity → t_rel.after = [chain[-1].id]."""
    prev = Entity.create("prev fact", EntityType.FACT, SourceType.AGENT)
    chain = [prev]
    temp = TemporalMarker(TimeRef.PRESENT, TimeRef.PAST, Explicitness.INFERRED, 0.8)
    t_rel = _build_t_rel(temp, chain)
    assert prev.id in t_rel.after
    assert t_rel.is_empty() is False


def test_build_t_rel_explicit_past():
    """Explicit past → also after the last chain entity."""
    prev = Entity.create("prev fact", EntityType.FACT, SourceType.AGENT)
    chain = [prev]
    temp = TemporalMarker(TimeRef.PAST, TimeRef.PAST, Explicitness.EXPLICIT, 1.0)
    t_rel = _build_t_rel(temp, chain)
    assert prev.id in t_rel.after


def test_build_t_rel_explicit_future():
    """Explicit future → before the last chain entity."""
    prev = Entity.create("planned entity", EntityType.EVENT, SourceType.AGENT)
    chain = [prev]
    temp = TemporalMarker(TimeRef.FUTURE, TimeRef.FUTURE, Explicitness.EXPLICIT, 1.0)
    t_rel = _build_t_rel(temp, chain)
    assert prev.id in t_rel.before


def test_build_t_rel_empty_chain():
    """No chain → always empty t_rel."""
    temp = TemporalMarker(TimeRef.PAST, TimeRef.PAST, Explicitness.EXPLICIT, 1.0)
    t_rel = _build_t_rel(temp, [])
    assert t_rel.is_empty()


def test_build_t_rel_unknown_temp_empty():
    """Unknown temporal → empty t_rel even with chain."""
    prev = Entity.create("something", EntityType.FACT, SourceType.AGENT)
    temp = TemporalMarker(TimeRef.UNKNOWN, TimeRef.UNKNOWN, Explicitness.LOST, 0.3)
    t_rel = _build_t_rel(temp, [prev])
    assert t_rel.is_empty()


@pytest.mark.asyncio
async def test_marker_fills_t_rel_from_chain():
    """marker() sets entity.t_rel.after when chain is provided and text is past-tense."""
    prev = Entity.create("previous decision", EntityType.DECISION, SourceType.AGENT)
    ctx = MagicMock()
    ctx.models = None

    result = await marker(
        "Yesterday we chose PostgreSQL",
        SourceType.AGENT, "s1", ctx,
        chain=[prev],
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert prev.id in result.entity.t_rel.after


@pytest.mark.asyncio
async def test_marker_t_rel_empty_no_chain():
    ctx = MagicMock()
    ctx.models = None
    result = await marker(
        "def process_data(x): return x",
        SourceType.AGENT, "s1", ctx,
        chain=[],
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert result.entity.t_rel.is_empty()


# ---------------------------------------------------------------------------
# 5.2 — pending_emotions registry
# ---------------------------------------------------------------------------

def _make_ctx_with_pending():
    ctx = MagicMock()
    ctx.models = None
    ctx.pending_emotions = []
    return ctx


@pytest.mark.asyncio
async def test_pending_emotion_added_when_no_chain():
    """Emotion with no chain entity → stays pending, added to ctx.pending_emotions."""
    ctx = _make_ctx_with_pending()

    result = await marker(
        "Terrible, everything is broken!",
        SourceType.AGENT, "s1", ctx,
        chain=[],
        pending_emotions=ctx.pending_emotions,
    )

    assert result.action == MarkerAction.CREATE_EMOTION
    assert result.emotion.pending is True
    # After the pipeline would do: ctx.pending_emotions.append(result.emotion)
    ctx.pending_emotions.append(result.emotion)
    assert len(ctx.pending_emotions) == 1


@pytest.mark.asyncio
async def test_pending_emotions_resolved_on_entity():
    """When entity arrives, pending emotions in list get resolved."""
    from mnemostroma.observer.marker import resolve_pending_emotions

    pending = Emotion.create(EmotionCharge.NEGATIVE, 0.7, pending=True)
    ctx = _make_ctx_with_pending()
    ctx.pending_emotions = [pending]

    result = await marker(
        "We decided to use MongoDB instead",
        SourceType.AGENT, "s1", ctx,
        chain=[],
        pending_emotions=ctx.pending_emotions,
    )

    assert result.action == MarkerAction.CREATE_ENTITY
    # All pending emotions should now be resolved (pending=False)
    assert pending.pending is False
    assert pending.ref_entity_id == result.entity.id


@pytest.mark.asyncio
async def test_pending_emotions_cleared_after_entity():
    """Pipeline simulation: pending list cleaned after entity resolves them."""
    pending = Emotion.create(EmotionCharge.POSITIVE, 0.8, pending=True)
    ctx = _make_ctx_with_pending()
    ctx.pending_emotions = [pending]

    result = await marker(
        "Deployment completed. Version 2.1.0 is now live in production.",
        SourceType.AGENT, "s1", ctx,
        chain=[],
        pending_emotions=ctx.pending_emotions,
    )

    # Simulate pipeline cleanup
    if result.action == MarkerAction.CREATE_ENTITY:
        ctx.pending_emotions = [e for e in ctx.pending_emotions if e.pending]

    assert len(ctx.pending_emotions) == 0  # resolved → cleared


# ---------------------------------------------------------------------------
# 5.4 — RAM eviction formula v2
# ---------------------------------------------------------------------------

def _make_sb(importance="important", intensity=0.0, age_days=1):
    now = int(time.time())
    return SessionBrief(
        session_id="s1",
        brief="test",
        tags=[],
        importance=importance,
        score=0.5,
        resolution=1.0,
        created_at=now - int(age_days * 86400),
        intensity=intensity,
    )


def test_eviction_priority_principle_highest():
    """principle > critical > important > background (higher priority = harder to evict)."""
    p = _eviction_priority(_make_sb("principle", age_days=1))
    c = _eviction_priority(_make_sb("critical", age_days=1))
    i = _eviction_priority(_make_sb("important", age_days=1))
    b = _eviction_priority(_make_sb("background", age_days=1))
    assert p > c > i > b


def test_eviction_priority_intensity_raises():
    """Higher emotion intensity → higher priority → harder to evict."""
    low  = _eviction_priority(_make_sb("important", intensity=0.0))
    high = _eviction_priority(_make_sb("important", intensity=0.9))
    assert high > low


def test_eviction_priority_recency_decays():
    """Older session → lower priority → evicted first."""
    fresh = _eviction_priority(_make_sb("important", age_days=0))
    old   = _eviction_priority(_make_sb("important", age_days=80))
    assert fresh > old


def test_eviction_priority_zero_at_90_days():
    """Session older than 90 days → recency_factor = 0 → priority = 0."""
    p = _eviction_priority(_make_sb("critical", age_days=91))
    assert p == 0.0


def test_eviction_priority_sort_order():
    """Sorting by _eviction_priority ascending puts background/old first."""
    sessions = [
        _make_sb("principle", age_days=1),
        _make_sb("background", age_days=89),
        _make_sb("critical", age_days=1),
        _make_sb("important", age_days=50),
    ]
    sessions.sort(key=_eviction_priority)
    # First (lowest priority) should be background old, last should be principle fresh
    assert sessions[0].importance == "background"
    assert sessions[-1].importance == "principle"


def test_importance_weight_coverage():
    """All standard importance strings have a weight defined."""
    for label in ("principle", "critical", "important", "background"):
        assert label in _IMPORTANCE_WEIGHT
        assert 0.0 < _IMPORTANCE_WEIGHT[label] <= 1.0
