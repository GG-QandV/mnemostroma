# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Sprint 1 — ctx_search, ctx_full, ctx_anchors, ctx_precision."""
import time
import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.tools.read import ctx_search, ctx_anchors, ctx_precision
from mnemostroma.storage.sqlite import DatabaseManager
from mnemostroma.adapters.sqlite.precision_repo import PrecisionRepo


# ── Shared fixtures ───────────────────────────────────────────────────────────

def _make_sb(session_id, tags, importance="important", score=0.5):
    return SessionBrief(
        session_id=session_id,
        brief=f"brief-{session_id}",
        tags=tags,
        importance=importance,
        score=score,
        resolution=1.0,
        created_at=int(time.time()),
    )


class _MockCtx:
    def __init__(self):
        self.ram_index = {}
        self.db = None
        self.anchor_index = None
        self.log_writer = None
        self.config = MagicMock()
        self.config.logging.enabled = False
        self.metrics = {}
        self.session_repo = None
        self.precision_repo = None
        self.anchor_repo = None


@pytest.fixture
def ctx():
    c = _MockCtx()
    c.ram_index = {
        "s1": _make_sb("s1", ["python", "backend"], importance="critical", score=0.9),
        "s2": _make_sb("s2", ["python", "api"], importance="important", score=0.7),
        "s3": _make_sb("s3", ["rust", "backend"], importance="background", score=0.3),
        "s4": _make_sb("s4", ["python", "backend", "auth"], importance="critical", score=0.8),
    }
    return c


# ── ctx_search ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_search_single_tag(ctx):
    result = await ctx_search(["python"], ctx)
    ids = {r.session_id for r in result}
    assert {"s1", "s2", "s4"} == ids


@pytest.mark.asyncio
async def test_ctx_search_intersection(ctx):
    result = await ctx_search(["python", "backend"], ctx)
    ids = {r.session_id for r in result}
    assert {"s1", "s4"} == ids


@pytest.mark.asyncio
async def test_ctx_search_no_match(ctx):
    result = await ctx_search(["elixir"], ctx)
    assert result == []


@pytest.mark.asyncio
async def test_ctx_search_importance_filter(ctx):
    result = await ctx_search(["python"], ctx, importance="critical")
    ids = {r.session_id for r in result}
    assert ids == {"s1", "s4"}


@pytest.mark.asyncio
async def test_ctx_search_sorted_by_score(ctx):
    result = await ctx_search(["python", "backend"], ctx)
    scores = [r.score for r in result]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_ctx_search_limit(ctx):
    result = await ctx_search(["python"], ctx, limit=2)
    assert len(result) <= 2


@pytest.mark.asyncio
async def test_ctx_search_empty_ram(ctx):
    ctx.ram_index = {}
    result = await ctx_search(["python"], ctx)
    assert result == []


# ── ctx_anchors ───────────────────────────────────────────────────────────────

class _MockAnchor:
    def __init__(self, anchor_id, anchor_type, session_id, brief="b"):
        self.anchor_id = anchor_id
        self.anchor_type = anchor_type
        self.session_id = session_id
        self.brief = brief
        self.key_facts = []
        self.flags = {}
        self.decay_level = 0
        self.access_count = 0
        self.last_accessed_at = int(time.time())
        self.t_rel = {"after": [], "before": [], "caused_by": [], "during": []}
        self.created_at = int(time.time())


class _MockAnchorIndex:
    def __init__(self, anchors):
        self._anchors = anchors

    def all(self):
        return list(self._anchors)

    def query_by_type(self, anchor_type):
        return [a for a in self._anchors if a.anchor_type == anchor_type]


@pytest.fixture
def ctx_with_anchors(ctx):
    anchors = [
        _MockAnchor("a1", "decision", "s1"),
        _MockAnchor("a2", "decision", "s2"),
        _MockAnchor("a3", "milestone", "s1"),
        _MockAnchor("a4", "observation", "s3"),
    ]
    ctx.anchor_index = _MockAnchorIndex(anchors)
    return ctx


@pytest.mark.asyncio
async def test_ctx_anchors_all(ctx_with_anchors):
    result = await ctx_anchors(ctx_with_anchors)
    assert len(result) == 4


@pytest.mark.asyncio
async def test_ctx_anchors_filter_type(ctx_with_anchors):
    result = await ctx_anchors(ctx_with_anchors, anchor_type="decision")
    assert len(result) == 2
    assert all(r["anchor_type"] == "decision" for r in result)


@pytest.mark.asyncio
async def test_ctx_anchors_filter_session(ctx_with_anchors):
    result = await ctx_anchors(ctx_with_anchors, session_id="s1")
    assert len(result) == 2
    assert all(r["session_id"] == "s1" for r in result)


@pytest.mark.asyncio
async def test_ctx_anchors_no_embedding_in_result(ctx_with_anchors):
    result = await ctx_anchors(ctx_with_anchors)
    for r in result:
        assert "embedding" not in r


@pytest.mark.asyncio
async def test_ctx_anchors_no_index(ctx):
    ctx.anchor_index = None
    result = await ctx_anchors(ctx)
    assert result == []


@pytest.mark.asyncio
async def test_ctx_anchors_limit(ctx_with_anchors):
    result = await ctx_anchors(ctx_with_anchors, limit=2)
    assert len(result) <= 2


# ── ctx_precision ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_precision_no_db(ctx):
    ctx.precision_repo = None
    result = await ctx_precision(ctx)
    assert result == []


@pytest.mark.asyncio
async def test_ctx_precision_with_db(ctx):
    """Test that ctx_precision correctly queries DB and returns structured rows."""
    import aiosqlite

    async with aiosqlite.connect(":memory:") as db:
        await db.execute("""
            CREATE TABLE precision_log (
                precision_id TEXT PRIMARY KEY,
                session_id TEXT,
                type TEXT,
                value TEXT,
                context_tag TEXT,
                importance TEXT,
                created_at INTEGER
            )
        """)
        await db.execute(
            "INSERT INTO precision_log VALUES (?,?,?,?,?,?,?)",
            ("p1", "s1", "link", "https://example.com", "backend", "critical", 1000)
        )
        await db.execute(
            "INSERT INTO precision_log VALUES (?,?,?,?,?,?,?)",
            ("p2", "s2", "formula", "E=mc²", "physics", "important", 999)
        )
        await db.commit()

        # Wrap in Manager and Repo
        mgr = DatabaseManager(db, ctx.config)
        ctx.precision_repo = PrecisionRepo(mgr)
        
        result = await ctx_precision(ctx)
        assert len(result) == 2
        assert any(r["type"] == "link" for r in result)
        assert any(r["type"] == "formula" for r in result)

        result_filtered = await ctx_precision(ctx, precision_type="link")
        assert len(result_filtered) == 1
        assert result_filtered[0]["value"] == "https://example.com"


# ── MCP routing coverage ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_list_tools_includes_sprint1():
    """Verify Sprint 1 tools appear in list_tools() output."""
    from mnemostroma.integration.mcp_server import list_tools

    tools = await list_tools()
    names = {t.name for t in tools}
    assert "ctx_search" in names
    assert "ctx_full" in names
    assert "ctx_anchors" in names
    assert "ctx_precision" in names
    # assert "ctx_expire" in names  # DISABLED 2026-04-14


@pytest.mark.asyncio
async def test_mcp_no_hnsw_in_descriptions():
    """No tool description should mention HNSW."""
    from mnemostroma.integration.mcp_server import list_tools

    tools = await list_tools()
    for t in tools:
        assert "HNSW" not in t.description, f"Tool {t.name} still mentions HNSW"
        assert "hnswlib" not in t.description.lower()
