# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for observer/entities.py — Memory Model v2 dataclasses."""
import time
import numpy as np
import pytest

from mnemostroma.observer.entities import (
    Entity, EntityType, SourceType, ResultType,
    Emotion, EmotionCharge,
    Atmosphere,
    TemporalMarker, TemporalRelations,
    TimeRef, Explicitness,
    MarkerResult, MarkerAction,
)


# ---------------------------------------------------------------------------
# TemporalMarker
# ---------------------------------------------------------------------------

def test_temporal_marker_unknown():
    tm = TemporalMarker.unknown()
    assert tm.gram_time == TimeRef.UNKNOWN
    assert tm.explicitness == Explicitness.LOST
    assert tm.confidence == 0.3


def test_temporal_marker_explicit():
    tm = TemporalMarker(TimeRef.PAST, TimeRef.PAST, Explicitness.EXPLICIT, 1.0)
    assert tm.ref_time == TimeRef.PAST
    assert tm.confidence == 1.0


# ---------------------------------------------------------------------------
# TemporalRelations
# ---------------------------------------------------------------------------

def test_temporal_relations_empty():
    tr = TemporalRelations()
    assert tr.is_empty()
    assert tr.all_ids() == []


def test_temporal_relations_all_ids():
    tr = TemporalRelations(after=["a"], caused_by=["b", "c"])
    ids = tr.all_ids()
    assert "a" in ids and "b" in ids and "c" in ids
    assert not tr.is_empty()


# ---------------------------------------------------------------------------
# Entity
# ---------------------------------------------------------------------------

def test_entity_create_defaults():
    e = Entity.create(
        what="We chose PostgreSQL",
        entity_type=EntityType.DECISION,
        source=SourceType.USER,
    )
    assert e.id  # non-empty uuid
    assert e.what == "We chose PostgreSQL"
    assert e.type == EntityType.DECISION
    assert e.source == SourceType.USER
    assert e.temp.explicitness == Explicitness.LOST  # unknown default
    assert e.importance == 0.5
    assert e.embedding is None
    assert e.result is None
    assert e.t_rel.is_empty()


def test_entity_create_with_temp():
    tm = TemporalMarker(TimeRef.PAST, TimeRef.PAST, Explicitness.EXPLICIT, 1.0)
    e = Entity.create(
        what="Decided to use Redis",
        entity_type=EntityType.DECISION,
        source=SourceType.AGENT,
        temp=tm,
        importance=0.9,
    )
    assert e.temp.gram_time == TimeRef.PAST
    assert e.importance == 0.9


def test_entity_with_embedding():
    vec = np.random.rand(384).astype(np.float32)
    e = Entity.create(
        what="some code artifact",
        entity_type=EntityType.CODE,
        source=SourceType.TOOL,
        embedding=vec,
    )
    assert e.embedding is not None
    assert e.embedding.shape == (384,)


def test_entity_unique_ids():
    e1 = Entity.create("a", EntityType.FACT, SourceType.USER)
    e2 = Entity.create("b", EntityType.FACT, SourceType.USER)
    assert e1.id != e2.id


# ---------------------------------------------------------------------------
# Emotion
# ---------------------------------------------------------------------------

def test_emotion_create_backward():
    em = Emotion.create(
        charge=EmotionCharge.POSITIVE,
        intensity=0.8,
        ref_entity_id="some-entity-id",
        ref_source=SourceType.USER,
    )
    assert em.charge == EmotionCharge.POSITIVE
    assert em.intensity == 0.8
    assert em.pending is False
    assert em.ref_entity_id == "some-entity-id"


def test_emotion_create_pending():
    em = Emotion.create(
        charge=EmotionCharge.NEGATIVE,
        intensity=0.6,
        pending=True,
    )
    assert em.pending is True
    assert em.ref_entity_id is None


# ---------------------------------------------------------------------------
# Atmosphere
# ---------------------------------------------------------------------------

def test_atmosphere_create():
    atm = Atmosphere.create(signals=["database", "migration", "schema"])
    assert atm.pending is True
    assert atm.entity_id is None
    assert "database" in atm.signals
    assert 0.0 <= atm.noise_level <= 1.0


# ---------------------------------------------------------------------------
# MarkerResult
# ---------------------------------------------------------------------------

def test_marker_result_discard():
    r = MarkerResult.discard()
    assert r.action == MarkerAction.DISCARD
    assert r.entity is None
    assert r.emotion is None
    assert r.atmosphere is None


def test_marker_result_with_entity():
    e = Entity.create("fact text", EntityType.FACT, SourceType.AGENT)
    r = MarkerResult(action=MarkerAction.CREATE_ENTITY, entity=e, confidence=0.9)
    assert r.action == MarkerAction.CREATE_ENTITY
    assert r.entity is e
    assert r.confidence == 0.9


def test_marker_result_with_emotion():
    em = Emotion.create(EmotionCharge.NEUTRAL, 0.5)
    r = MarkerResult(action=MarkerAction.CREATE_EMOTION, emotion=em, confidence=0.7)
    assert r.action == MarkerAction.CREATE_EMOTION
    assert r.emotion.charge == EmotionCharge.NEUTRAL
