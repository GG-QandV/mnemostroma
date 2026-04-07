# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for observer/marker.py — Memory Model v2 marker() function."""
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass

from mnemostroma.observer.entities import (
    Entity, EntityType, SourceType,
    Emotion, EmotionCharge,
    TemporalMarker, TimeRef, Explicitness,
    MarkerAction,
)
from mnemostroma.observer.marker import (
    infer_temporal,
    bind_emotion,
    resolve_pending_emotions,
    marker,
    _detect_emotion_charge,
    _keyword_classify,
    _classify,
    ANCHORS,
)


# ---------------------------------------------------------------------------
# Minimal mock context
# ---------------------------------------------------------------------------

def _make_ctx(embedder=None):
    ctx = MagicMock()
    ctx.models = MagicMock()
    ctx.models.embedder = embedder
    return ctx


def _make_embedder(vec=None):
    """Embedder that always returns the given vector (or zeros)."""
    if vec is None:
        vec = np.zeros(384, dtype=np.float32)
    emb = MagicMock()
    emb.aencode = AsyncMock(return_value=vec)
    return emb


# ---------------------------------------------------------------------------
# infer_temporal
# ---------------------------------------------------------------------------

def test_infer_temporal_explicit_past_en():
    tm = infer_temporal("We decided yesterday", [])
    assert tm.gram_time == TimeRef.PAST
    assert tm.ref_time == TimeRef.PAST
    assert tm.explicitness == Explicitness.EXPLICIT


def test_infer_temporal_explicit_past_ru():
    tm = infer_temporal("Вчера мы выбрали PostgreSQL", [])
    assert tm.gram_time == TimeRef.PAST


def test_infer_temporal_explicit_future_en():
    tm = infer_temporal("We will deploy tomorrow", [])
    assert tm.gram_time == TimeRef.FUTURE
    assert tm.ref_time == TimeRef.FUTURE
    assert tm.explicitness == Explicitness.EXPLICIT


def test_infer_temporal_explicit_future_ru():
    tm = infer_temporal("Завтра переедем на новый сервер", [])
    assert tm.gram_time == TimeRef.FUTURE


def test_infer_temporal_inferred_from_chain():
    chain = [Entity.create("some prior fact", EntityType.FACT, SourceType.AGENT)]
    tm = infer_temporal("It does not work", chain)
    assert tm.gram_time == TimeRef.PRESENT
    assert tm.ref_time == TimeRef.PAST
    assert tm.explicitness == Explicitness.INFERRED
    assert tm.confidence == 0.8


def test_infer_temporal_unknown():
    tm = infer_temporal("Connects to the system", [])
    assert tm.explicitness == Explicitness.LOST
    assert tm.confidence == 0.3


# ---------------------------------------------------------------------------
# bind_emotion
# ---------------------------------------------------------------------------

def test_bind_emotion_backward():
    entity = Entity.create("we chose Redis", EntityType.DECISION, SourceType.AGENT)
    chain = [entity]
    em = Emotion.create(EmotionCharge.POSITIVE, 0.8, pending=True)
    result = bind_emotion(em, chain)
    assert result.pending is False
    assert result.ref_entity_id == entity.id
    assert result.ref_source == SourceType.AGENT


def test_bind_emotion_no_chain_stays_pending():
    em = Emotion.create(EmotionCharge.NEGATIVE, 0.7, pending=True)
    result = bind_emotion(em, [])
    assert result.pending is True
    assert result.ref_entity_id is None


def test_bind_emotion_prefers_agent_over_user():
    user_entity = Entity.create("user message", EntityType.FACT, SourceType.USER)
    agent_entity = Entity.create("agent response", EntityType.FACT, SourceType.AGENT)
    chain = [user_entity, agent_entity]
    em = Emotion.create(EmotionCharge.POSITIVE, 0.5, pending=True)
    result = bind_emotion(em, chain)
    assert result.ref_source == SourceType.AGENT


# ---------------------------------------------------------------------------
# resolve_pending_emotions
# ---------------------------------------------------------------------------

def test_resolve_pending_emotions():
    e1 = Emotion.create(EmotionCharge.POSITIVE, 0.8, pending=True)
    e2 = Emotion.create(EmotionCharge.NEGATIVE, 0.6, pending=True)
    entity = Entity.create("result arrived", EntityType.RESULT, SourceType.AGENT)
    resolve_pending_emotions(entity, [e1, e2])
    assert e1.pending is False
    assert e1.ref_entity_id == entity.id
    assert e2.pending is False
    assert e2.ref_entity_id == entity.id


# ---------------------------------------------------------------------------
# _detect_emotion_charge
# ---------------------------------------------------------------------------

def test_detect_charge_positive():
    charge, intensity = _detect_emotion_charge("Finally it works, great!")
    assert charge == EmotionCharge.POSITIVE
    assert intensity > 0.4


def test_detect_charge_negative():
    charge, intensity = _detect_emotion_charge("This is terrible, completely broken")
    assert charge == EmotionCharge.NEGATIVE
    assert intensity > 0.4


def test_detect_charge_neutral():
    charge, _ = _detect_emotion_charge("The function processes data")
    assert charge == EmotionCharge.NEUTRAL


# ---------------------------------------------------------------------------
# _keyword_classify
# ---------------------------------------------------------------------------

def test_keyword_classify_code():
    assert _keyword_classify("def process_data(x):") == EntityType.CODE.value


def test_keyword_classify_decision():
    assert _keyword_classify("We decided to use Postgres") == EntityType.DECISION.value


def test_keyword_classify_emotion():
    assert _keyword_classify("Finally it works!") == "emotion"


def test_keyword_classify_fallback():
    assert _keyword_classify("some random text here") == EntityType.FACT.value


# ---------------------------------------------------------------------------
# marker() — async, user role
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_marker_hard_discard():
    ctx = _make_ctx()
    result = await marker("hi", SourceType.USER, "s1", ctx)
    assert result.action == MarkerAction.DISCARD


@pytest.mark.asyncio
async def test_marker_user_creates_entity():
    ctx = _make_ctx(_make_embedder())
    result = await marker(
        "We need to add authentication to the API",
        SourceType.USER, "s1", ctx,
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert result.entity is not None
    assert result.entity.source == SourceType.USER
    assert result.entity.importance == 0.7


@pytest.mark.asyncio
async def test_marker_user_resolves_pending_emotions():
    ctx = _make_ctx(_make_embedder())
    pending_em = Emotion.create(EmotionCharge.POSITIVE, 0.8, pending=True)
    result = await marker(
        "We chose Redis for caching",
        SourceType.USER, "s1", ctx,
        pending_emotions=[pending_em],
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert pending_em.pending is False
    assert pending_em.ref_entity_id == result.entity.id


# ---------------------------------------------------------------------------
# marker() — async, agent role with real classify
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_marker_agent_creates_entity():
    vec = np.random.rand(384).astype(np.float32)
    ctx = _make_ctx(_make_embedder(vec))
    result = await marker(
        "The system decided to use PostgreSQL as the primary database",
        SourceType.AGENT, "s1", ctx,
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert result.entity is not None
    assert result.entity.source == SourceType.AGENT
    assert result.entity.embedding is not None


@pytest.mark.asyncio
async def test_marker_agent_no_embedder_uses_keywords():
    ctx = _make_ctx(embedder=None)
    ctx.models = None  # fully disable models
    result = await marker(
        "def process_data(items): return items",
        SourceType.AGENT, "s1", ctx,
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert result.entity.type == EntityType.CODE


@pytest.mark.asyncio
async def test_marker_temporal_past_in_agent():
    ctx = _make_ctx(_make_embedder())
    result = await marker(
        "Yesterday we deployed the service and it worked",
        SourceType.AGENT, "s1", ctx,
    )
    assert result.action == MarkerAction.CREATE_ENTITY
    assert result.entity.temp.gram_time == TimeRef.PAST


@pytest.mark.asyncio
async def test_marker_classify_uses_anchor_vectors():
    """_classify returns highest-cosine anchor label."""
    from mnemostroma.observer.marker import _classify
    # Build mock anchor_vecs: only decision and fact
    decision_vec = np.array([1.0, 0.0, 0.0], dtype=np.float32)
    fact_vec     = np.array([0.0, 1.0, 0.0], dtype=np.float32)
    anchor_vecs  = {"decision": decision_vec, "fact": fact_vec}

    query = np.array([0.99, 0.01, 0.0], dtype=np.float32)
    label, conf = _classify(query, anchor_vecs)
    assert label == "decision"
    assert conf > 0.9
