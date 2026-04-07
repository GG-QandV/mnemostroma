# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Sprint 2 content tools — content_get, content_raw, content_history."""
import json
import time
import pytest
import lz4.frame
from unittest.mock import MagicMock

import aiosqlite

from mnemostroma.tools.content import content_get, content_raw, content_history


# ── DB fixture ────────────────────────────────────────────────────────────────

def _compress(text: str) -> bytes:
    return lz4.frame.compress(text.encode("utf-8"))


async def _make_db():
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE content_blocks (
            content_id TEXT PRIMARY KEY,
            session_id TEXT, content_type TEXT,
            parent_id TEXT, project_id TEXT, status TEXT
        )
    """)
    await db.execute("""
        CREATE TABLE content_versions (
            content_id TEXT, version INTEGER,
            content_hash TEXT, content_raw BLOB,
            content_diff TEXT, content_tags TEXT,
            tags_verified INTEGER DEFAULT 0,
            why_changed TEXT, status TEXT,
            rejected_reason TEXT, embedding BLOB,
            embedding_model_version TEXT,
            created_at INTEGER,
            PRIMARY KEY (content_id, version)
        )
    """)
    # Insert test data
    await db.execute(
        "INSERT INTO content_blocks VALUES (?,?,?,?,?,?)",
        ("auth_module", "s1", "function", None, "proj1", "active")
    )
    await db.execute(
        "INSERT INTO content_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("auth_module", 1, "hash1", _compress("def login(): pass"),
         None, '["auth","python"]', 0, "initial", "active",
         None, None, None, 1000)
    )
    await db.execute(
        "INSERT INTO content_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("auth_module", 2, "hash2", _compress("def login(user): return True"),
         "+user param", '["auth","python"]', 0, "add user param", "active",
         None, None, None, 2000)
    )
    await db.execute(
        "INSERT INTO content_versions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("auth_module", 3, "hash3", _compress("BAD CODE"),
         None, '["auth"]', 0, "broken attempt", "rejected",
         "syntax error", None, None, 3000)
    )
    await db.commit()
    return db


class _MockCtx:
    def __init__(self, db):
        self.db = db
        self.content = None
        self.log_writer = None
        self.config = MagicMock()
        self.config.logging.enabled = False
        self.metrics = {}


# ── content_get ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_get_latest_active():
    db = await _make_db()
    ctx = _MockCtx(db)
    result = await content_get("auth_module", ctx)
    assert result is not None
    assert result["content_id"] == "auth_module"
    assert result["version"] == 2          # latest active (v3 is rejected)
    assert result["version_status"] == "active"
    await db.close()


@pytest.mark.asyncio
async def test_content_get_specific_version():
    db = await _make_db()
    ctx = _MockCtx(db)
    result = await content_get("auth_module", ctx, version=1)
    assert result is not None
    assert result["version"] == 1
    await db.close()


@pytest.mark.asyncio
async def test_content_get_not_found():
    db = await _make_db()
    ctx = _MockCtx(db)
    result = await content_get("nonexistent", ctx)
    assert result is None
    await db.close()


@pytest.mark.asyncio
async def test_content_get_no_db():
    ctx = _MockCtx(None)
    result = await content_get("auth_module", ctx)
    assert result is None


@pytest.mark.asyncio
async def test_content_get_tags_parsed():
    db = await _make_db()
    ctx = _MockCtx(db)
    result = await content_get("auth_module", ctx)
    assert isinstance(result["content_tags"], list)
    assert "auth" in result["content_tags"]
    await db.close()


# ── content_raw ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_raw_latest_active():
    db = await _make_db()
    ctx = _MockCtx(db)
    text = await content_raw("auth_module", ctx)
    assert text == "def login(user): return True"
    await db.close()


@pytest.mark.asyncio
async def test_content_raw_specific_version():
    db = await _make_db()
    ctx = _MockCtx(db)
    text = await content_raw("auth_module", ctx, version=1)
    assert text == "def login(): pass"
    await db.close()


@pytest.mark.asyncio
async def test_content_raw_not_found():
    db = await _make_db()
    ctx = _MockCtx(db)
    text = await content_raw("nonexistent", ctx)
    assert text is None
    await db.close()


@pytest.mark.asyncio
async def test_content_raw_no_db():
    ctx = _MockCtx(None)
    result = await content_raw("auth_module", ctx)
    assert result is None


# ── content_history ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_history_all_versions():
    db = await _make_db()
    ctx = _MockCtx(db)
    history = await content_history("auth_module", ctx)
    assert len(history) == 3
    versions = [h["version"] for h in history]
    assert versions == [1, 2, 3]
    await db.close()


@pytest.mark.asyncio
async def test_content_history_includes_rejected():
    db = await _make_db()
    ctx = _MockCtx(db)
    history = await content_history("auth_module", ctx)
    statuses = {h["status"] for h in history}
    assert "rejected" in statuses
    assert "active" in statuses
    await db.close()


@pytest.mark.asyncio
async def test_content_history_rejected_reason():
    db = await _make_db()
    ctx = _MockCtx(db)
    history = await content_history("auth_module", ctx)
    rejected = next(h for h in history if h["status"] == "rejected")
    assert rejected["rejected_reason"] == "syntax error"
    await db.close()


@pytest.mark.asyncio
async def test_content_history_no_raw_text():
    """History must never include raw content blobs."""
    db = await _make_db()
    ctx = _MockCtx(db)
    history = await content_history("auth_module", ctx)
    for h in history:
        assert "content_raw" not in h
        assert "embedding" not in h
    await db.close()


@pytest.mark.asyncio
async def test_content_history_empty_for_unknown():
    db = await _make_db()
    ctx = _MockCtx(db)
    history = await content_history("nonexistent", ctx)
    assert history == []
    await db.close()


@pytest.mark.asyncio
async def test_content_history_no_db():
    ctx = _MockCtx(None)
    result = await content_history("auth_module", ctx)
    assert result == []
