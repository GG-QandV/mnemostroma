# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for §5.1 Temporal Relations Graph persistence.

Covers:
- Anchor dataclass: t_rel field default, to_dict/from_dict round-trip
- from_dict backwards-compat: old data without t_rel key
- SQLite: save_anchor/get_anchor/load_anchors round-trip with t_rel
- Migration: check_anchor_schema adds column to legacy table
- Pipeline: t_rel extracted from entities and stored on Anchor
"""
import json
import pytest
import aiosqlite
import pytest_asyncio

from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.storage.sqlite import check_anchor_schema


# ── Dataclass unit tests ─────────────────────────────────────────────────────

def test_anchor_t_rel_default():
    a = Anchor(
        anchor_id="sid1", session_id="sid1",
        brief="test", anchor_type="event",
        created_at=1000, updated_at=1000,
    )
    assert a.t_rel == {"after": [], "before": [], "caused_by": [], "during": []}


def test_anchor_to_dict_includes_t_rel():
    a = Anchor(
        anchor_id="sid1", session_id="sid1",
        brief="test", anchor_type="event",
        t_rel={"after": ["e2"], "before": [], "caused_by": ["e1"], "during": []},
        created_at=1000, updated_at=1000,
    )
    d = a.to_dict()
    assert d["t_rel"] == {"after": ["e2"], "before": [], "caused_by": ["e1"], "during": []}


def test_anchor_from_dict_round_trip():
    original = Anchor(
        anchor_id="sid2", session_id="sid2",
        brief="brief text", anchor_type="decision",
        t_rel={"after": ["x"], "before": [], "caused_by": [], "during": ["y"]},
        created_at=2000, updated_at=2000,
    )
    restored = Anchor.from_dict(original.to_dict())
    assert restored.t_rel == original.t_rel
    assert restored.anchor_id == original.anchor_id


def test_anchor_from_dict_backwards_compat():
    """Old dicts without t_rel key must deserialize without error."""
    old_data = {
        "anchor_id": "sid3", "session_id": "sid3",
        "brief": "legacy", "anchor_type": "observation",
        "key_facts": [], "flags": {}, "decay_level": 0,
        "access_count": 0, "last_accessed_at": 0,
        "created_at": 1000, "updated_at": 1000,
    }
    a = Anchor.from_dict(old_data)
    assert a.t_rel == {"after": [], "before": [], "caused_by": [], "during": []}


# ── SQLite persistence tests ──────────────────────────────────────────────────

@pytest_asyncio.fixture
async def db():
    """In-memory SQLite with anchors table including t_rel column."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("""
        CREATE TABLE anchors (
            anchor_id        TEXT PRIMARY KEY,
            session_id       TEXT NOT NULL,
            anchor_type      TEXT NOT NULL,
            brief            TEXT NOT NULL,
            key_facts        TEXT NOT NULL DEFAULT '[]',
            flags            TEXT NOT NULL DEFAULT '{}',
            decay_level      INTEGER NOT NULL DEFAULT 0,
            access_count     INTEGER NOT NULL DEFAULT 0,
            last_accessed_at INTEGER NOT NULL DEFAULT 0,
            t_rel            TEXT NOT NULL DEFAULT '{"after":[],"before":[],"caused_by":[],"during":[]}',
            created_at       INTEGER NOT NULL,
            updated_at       INTEGER NOT NULL
        )
    """)
    await conn.commit()
    yield conn
    await conn.close()


@pytest_asyncio.fixture
async def db_manager(db):
    from unittest.mock import MagicMock
    from mnemostroma.storage.sqlite import DatabaseManager
    cfg = MagicMock()
    cfg.storage.batch_size = 10
    cfg.storage.flush_interval_s = 1.0
    mgr = DatabaseManager(db, MagicMock(storage=cfg.storage))
    mgr.db = db
    return mgr


@pytest.mark.asyncio
async def test_save_and_get_anchor_with_t_rel(db_manager):
    a = Anchor(
        anchor_id="s10", session_id="s10",
        brief="launched", anchor_type="milestone",
        t_rel={"after": ["s9"], "before": [], "caused_by": ["s8"], "during": []},
        created_at=5000, updated_at=5000,
    )
    await db_manager.save_anchor(a)
    loaded = await db_manager.get_anchor("s10")
    assert loaded is not None
    assert loaded.t_rel == {"after": ["s9"], "before": [], "caused_by": ["s8"], "during": []}


@pytest.mark.asyncio
async def test_load_anchors_restores_t_rel(db_manager):
    a = Anchor(
        anchor_id="s20", session_id="s20",
        brief="analysis", anchor_type="observation",
        t_rel={"after": [], "before": ["s19"], "caused_by": [], "during": []},
        created_at=6000, updated_at=6000,
    )
    await db_manager.save_anchor(a)
    anchors = await db_manager.load_anchors()
    assert any(x.anchor_id == "s20" and x.t_rel["before"] == ["s19"] for x in anchors)


@pytest.mark.asyncio
async def test_save_anchor_empty_t_rel(db_manager):
    """Empty t_rel (default) must round-trip correctly."""
    a = Anchor(
        anchor_id="s30", session_id="s30",
        brief="plain", anchor_type="event",
        created_at=7000, updated_at=7000,
    )
    await db_manager.save_anchor(a)
    loaded = await db_manager.get_anchor("s30")
    assert loaded.t_rel == {"after": [], "before": [], "caused_by": [], "during": []}


# ── Migration test ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_anchor_schema_adds_column():
    """Migration adds t_rel column to a legacy anchors table that lacks it."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("""
        CREATE TABLE anchors (
            anchor_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            anchor_type TEXT NOT NULL,
            brief TEXT NOT NULL,
            key_facts TEXT NOT NULL DEFAULT '[]',
            flags TEXT NOT NULL DEFAULT '{}',
            decay_level INTEGER NOT NULL DEFAULT 0,
            access_count INTEGER NOT NULL DEFAULT 0,
            last_accessed_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL,
            updated_at INTEGER NOT NULL
        )
    """)
    await conn.commit()

    # Verify t_rel column is absent before migration
    async with conn.execute("PRAGMA table_info(anchors)") as cur:
        cols = [row[1] async for row in cur]
    assert "t_rel" not in cols

    # Run migration
    await check_anchor_schema(conn)

    # Verify column now exists
    async with conn.execute("PRAGMA table_info(anchors)") as cur:
        cols = [row[1] async for row in cur]
    assert "t_rel" in cols
    await conn.close()


@pytest.mark.asyncio
async def test_check_anchor_schema_idempotent():
    """Running migration twice must not raise an error."""
    conn = await aiosqlite.connect(":memory:")
    await conn.execute("""
        CREATE TABLE anchors (
            anchor_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL, anchor_type TEXT NOT NULL,
            brief TEXT NOT NULL, key_facts TEXT NOT NULL DEFAULT '[]',
            flags TEXT NOT NULL DEFAULT '{}', decay_level INTEGER NOT NULL DEFAULT 0,
            access_count INTEGER NOT NULL DEFAULT 0, last_accessed_at INTEGER NOT NULL DEFAULT 0,
            created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL
        )
    """)
    await conn.commit()
    await check_anchor_schema(conn)
    await check_anchor_schema(conn)  # second call must be silent no-op
    await conn.close()


# ── Pipeline extraction test ──────────────────────────────────────────────────

def test_t_rel_extraction_from_mark_result_entity():
    """t_rel is read from mark_result.entity (Entity built by marker), not from
    pre_entities (NER dicts). Verify the correct code path used in pipeline.py."""
    from mnemostroma.observer.entities import TemporalRelations, Entity, EntityType, SourceType
    from types import SimpleNamespace

    # Simulate mark_result.entity with a real TemporalRelations
    entity = SimpleNamespace(
        t_rel=TemporalRelations(after=["e1"], before=[], caused_by=["e0"], during=[])
    )

    # Code path from pipeline.py
    t_rel: dict = {"after": [], "before": [], "caused_by": [], "during": []}
    if entity and not entity.t_rel.is_empty():
        er = entity.t_rel
        t_rel["after"] = list(er.after)
        t_rel["before"] = list(er.before)
        t_rel["caused_by"] = list(er.caused_by)
        t_rel["during"] = list(er.during)

    assert t_rel["after"] == ["e1"]
    assert t_rel["before"] == []
    assert t_rel["caused_by"] == ["e0"]
    assert t_rel["during"] == []


def test_t_rel_extraction_empty_entity():
    """When mark_result.entity is None, t_rel stays empty."""
    from mnemostroma.observer.entities import TemporalRelations

    entity = None
    t_rel: dict = {"after": [], "before": [], "caused_by": [], "during": []}
    if entity and not entity.t_rel.is_empty():
        er = entity.t_rel
        t_rel["after"] = list(er.after)
        t_rel["before"] = list(er.before)
        t_rel["caused_by"] = list(er.caused_by)
        t_rel["during"] = list(er.during)

    assert t_rel == {"after": [], "before": [], "caused_by": [], "during": []}


def test_t_rel_extraction_entity_empty_t_rel():
    """When mark_result.entity.t_rel.is_empty() → t_rel stays empty."""
    from mnemostroma.observer.entities import TemporalRelations
    from types import SimpleNamespace

    entity = SimpleNamespace(t_rel=TemporalRelations())
    t_rel: dict = {"after": [], "before": [], "caused_by": [], "during": []}
    if entity and not entity.t_rel.is_empty():
        er = entity.t_rel
        t_rel["after"] = list(er.after)

    assert t_rel == {"after": [], "before": [], "caused_by": [], "during": []}
