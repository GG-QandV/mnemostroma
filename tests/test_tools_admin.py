# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Sprint 2+3 admin tools — ctx_evict, ctx_load, ctx_growth, ctx_pulse, ctx_bridge."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import aiosqlite

from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.tools.admin import ctx_evict, ctx_load, ctx_growth, ctx_pulse, ctx_bridge


def _make_sb(session_id, importance="important", score=0.5):
    return SessionBrief(
        session_id=session_id,
        brief=f"brief-{session_id}",
        tags=["test"],
        importance=importance,
        score=score,
        resolution=1.0,
        created_at=int(time.time()),
    )


class _MockCtx:
    def __init__(self):
        self.ram_index = {}
        self.sid_to_id = {}
        self.id_to_sid = {}
        self.db = None
        self._next_session_label = 0
        self.log_writer = None
        self.config = MagicMock()
        self.config.logging.enabled = False
        self.metrics = {}

    def get_session_label(self, session_id: str) -> int:
        if session_id not in self.sid_to_id:
            label = self._next_session_label
            self._next_session_label += 1
            self.sid_to_id[session_id] = label
            self.id_to_sid[label] = session_id
        return self.sid_to_id[session_id]


# ── ctx_evict (delegation wrapper) ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_evict_no_dissolver_returns_zero():
    """ctx_evict returns 0 when ctx has no dissolver — no standalone logic."""
    ctx = _MockCtx()
    ctx.ram_index["s0"] = _make_sb("s0", score=0.1)
    evicted = await ctx_evict(ctx, n=1)
    assert evicted == 0


@pytest.mark.asyncio
async def test_ctx_evict_delegates_to_dissolver():
    """ctx_evict calls dissolver.evict_n_oldest and returns count diff."""
    ctx = _MockCtx()
    ctx.ram_index["s0"] = _make_sb("s0", score=0.1)

    dissolver_mock = MagicMock()
    async def fake_evict(n):
        ctx.ram_index.pop("s0", None)
    dissolver_mock.evict_n_oldest = fake_evict
    ctx.dissolver = dissolver_mock

    evicted = await ctx_evict(ctx, n=1)
    assert evicted == 1


# ── ctx_load ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_load_already_in_ram():
    ctx = _MockCtx()
    sb = _make_sb("existing")
    ctx.ram_index["existing"] = sb
    result = await ctx_load("existing", ctx)
    assert result is sb


@pytest.mark.asyncio
async def test_ctx_load_no_db():
    ctx = _MockCtx()
    result = await ctx_load("missing", ctx)
    assert result is None


@pytest.mark.asyncio
async def test_ctx_load_from_sqlite():
    import json as _json
    db = await aiosqlite.connect(":memory:")
    await db.execute("""
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            created_at INTEGER, importance TEXT,
            tags TEXT, brief TEXT, conflict INTEGER,
            embedding BLOB
        )
    """)
    await db.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
        ("s_cold", int(time.time()), "important",
         _json.dumps(["tag1"]), "cold brief", 0, None)
    )
    await db.commit()

    ctx = _MockCtx()
    ctx.db = db

    result = await ctx_load("s_cold", ctx)
    assert result is not None
    assert result.session_id == "s_cold"
    assert result.brief == "cold brief"
    # Should be added to RAM
    assert "s_cold" in ctx.ram_index
    # Should be in label mappings
    assert "s_cold" in ctx.sid_to_id
    await db.close()


@pytest.mark.asyncio
async def test_ctx_load_not_in_sqlite():
    db = await aiosqlite.connect(":memory:")
    await db.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at INTEGER, "
        "importance TEXT, tags TEXT, brief TEXT, conflict INTEGER, embedding BLOB)"
    )
    await db.commit()

    ctx = _MockCtx()
    ctx.db = db
    result = await ctx_load("ghost", ctx)
    assert result is None
    await db.close()


# ── ctx_growth ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_growth_no_db():
    ctx = _MockCtx()
    result = await ctx_growth(ctx)
    assert result["sessions_total"] == 0
    assert result["db_size_mb"] == 0.0


@pytest.mark.asyncio
async def test_ctx_growth_with_sessions():
    import json as _json
    db = await aiosqlite.connect(":memory:")
    await db.execute(
        "CREATE TABLE sessions (session_id TEXT PRIMARY KEY, created_at INTEGER, "
        "importance TEXT, tags TEXT, brief TEXT, conflict INTEGER, embedding BLOB)"
    )
    now = int(time.time())
    for i in range(5):
        await db.execute(
            "INSERT INTO sessions VALUES (?,?,?,?,?,?,?)",
            (f"s{i}", now - i * 3600, "important", _json.dumps([]), f"brief{i}", 0, None)
        )
    await db.commit()

    ctx = _MockCtx()
    ctx.db = db
    result = await ctx_growth(ctx)
    assert result["sessions_total"] == 5
    assert result["sessions_today"] == 5
    assert result["sessions_week"] == 5
    assert result["sessions_month"] == 5
    await db.close()


@pytest.mark.asyncio
async def test_ctx_growth_returns_required_keys():
    ctx = _MockCtx()
    result = await ctx_growth(ctx)
    for key in ("sessions_total", "sessions_today", "sessions_week",
                "sessions_month", "db_size_mb"):
        assert key in result


# ── ctx_pulse ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_pulse_returns_sessions_count():
    ctx = _MockCtx()
    ctx.ram_index = {f"s{i}": _make_sb(f"s{i}") for i in range(7)}
    ctx.urgency_index = {}
    result = await ctx_pulse(ctx)
    assert result["sessions"] == 7


@pytest.mark.asyncio
async def test_ctx_pulse_ram_mb_non_negative():
    ctx = _MockCtx()
    ctx.ram_index = {}
    ctx.urgency_index = {}
    result = await ctx_pulse(ctx)
    assert result["ram_mb"] >= 0
    assert result["ram_pct"] >= 0


@pytest.mark.asyncio
async def test_ctx_pulse_urgency_count():
    ctx = _MockCtx()
    ctx.ram_index = {}
    ctx.urgency_index = {
        "u1": {"expired": False, "deadline_ts": int(time.time()) + 3600},
        "u2": {"expired": True,  "deadline_ts": int(time.time()) - 1},
    }
    result = await ctx_pulse(ctx)
    assert result["urgency_active"] == 1  # only non-expired


# ── ctx_bridge ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ctx_bridge_structure():
    ctx = _MockCtx()
    ctx.urgency_index = {}
    ctx.ram_index = {
        "s1": _make_sb("s1", importance="critical", score=0.9),
        "s2": _make_sb("s2", importance="important", score=0.7),
    }
    result = await ctx_bridge(ctx)
    assert "intent_summary" in result
    assert "active_variables" in result
    assert "last_decisions" in result
    assert "open_issues" in result
    assert "urgency_active" in result
    assert "ram_sessions" in result


@pytest.mark.asyncio
async def test_ctx_bridge_active_variables_critical_only():
    ctx = _MockCtx()
    ctx.urgency_index = {}
    ctx.ram_index = {
        "s1": _make_sb("s1", importance="critical", score=0.9),
        "s2": _make_sb("s2", importance="background", score=0.2),
    }
    result = await ctx_bridge(ctx)
    labels = result["active_variables"]
    assert any("[critical]" in v for v in labels)
    assert not any("[background]" in v for v in labels)


@pytest.mark.asyncio
async def test_ctx_bridge_empty_ram():
    ctx = _MockCtx()
    ctx.urgency_index = {}
    result = await ctx_bridge(ctx)
    assert result["ram_sessions"] == 0
    assert result["intent_summary"] == "No active sessions."


@pytest.mark.asyncio
async def test_ctx_bridge_open_issues_conflict_only():
    ctx = _MockCtx()
    ctx.urgency_index = {}
    sb_conflict = _make_sb("c1", importance="important", score=0.5)
    sb_conflict.conflict_flag = True
    sb_normal = _make_sb("n1", importance="important", score=0.5)
    ctx.ram_index = {"c1": sb_conflict, "n1": sb_normal}
    result = await ctx_bridge(ctx)
    assert len(result["open_issues"]) == 1


# ── MCP Sprint 3 routing ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_list_tools_agent_only():
    """MCP exposes only agent tools — daemon-only functions must not be present."""
    from mnemostroma.integration.mcp_server import list_tools
    tools = await list_tools()
    names = {t.name for t in tools}
    # Daemon-only — must NOT be in MCP
    for daemon_tool in ("ctx_growth", "ctx_pulse", "ctx_status", "ctx_sync",
                        "ctx_inject", "ctx_dump", "ctx_evict"):
        assert daemon_tool not in names, f"{daemon_tool} должен быть убран из MCP"
    # Agent tools — must be present
    assert "ctx_bridge" in names
    # assert "ctx_expire" in names  # DISABLED 2026-04-14
    # assert "ctx_urgent" in names  # DISABLED 2026-04-14
    # assert "save_content" in names # DISABLED 2026-04-14
