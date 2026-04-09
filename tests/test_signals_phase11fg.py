# SPDX-License-Identifier: FSL-1.1-MIT
import time
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.tools.read import ctx_active, _compute_urgency_level, _is_farewell

def _make_sb(session_id, importance="important", created_at=None):
    return SessionBrief(
        session_id=session_id,
        brief=f"brief-{session_id}",
        tags=["test"],
        importance=importance,
        score=0.5,
        resolution=1.0,
        created_at=created_at or int(time.time()),
    )

class _MockCtx:
    def __init__(self):
        self.ram_index = {}
        self.urgency_index = {}
        self.urgency_level_cache = {}
        self.closure_cooldown_until = 0.0
        self.last_message_text = ""
        self.config = MagicMock()
        self.config.urgency_pulse.enabled = True
        self.config.session_closure.enabled = True
        self.config.session_closure.cooldown_sec = 1800.0
        self.log_writer = None

# --- Tests for Phase 11.F (Urgency Pulse) ---

def test_compute_urgency_level_boundaries():
    now = time.time()
    # overdue: h <= 0
    assert _compute_urgency_level(now - 1) == "overdue"
    assert _compute_urgency_level(now) == "overdue"
    # critical: 0 < h <= 6
    assert _compute_urgency_level(now + 2 * 3600) == "critical"
    assert _compute_urgency_level(now + 6 * 3600) == "critical"
    # high: 6 < h <= 24
    assert _compute_urgency_level(now + 7 * 3600) == "high"
    assert _compute_urgency_level(now + 24 * 3600) == "high"
    # medium: 24 < h <= 72
    assert _compute_urgency_level(now + 25 * 3600) == "medium"
    assert _compute_urgency_level(now + 72 * 3600) == "medium"
    # low: h > 72
    assert _compute_urgency_level(now + 73 * 3600) == "low"

@pytest.mark.asyncio
async def test_urgency_pulse_new_item():
    ctx = _MockCtx()
    now = time.time()
    ctx.urgency_index = {
        "s1": {"value": "Fix bug", "deadline_ts": now + 5 * 3600, "expired": False}
    }
    
    res = await ctx_active(ctx)
    assert "urgency_pulse" in res
    assert len(res["urgency_pulse"]) == 1
    assert res["urgency_pulse"][0]["session_id"] == "s1"
    assert res["urgency_pulse"][0]["level"] == "critical"
    assert res["urgency_pulse"][0]["prev_level"] is None
    assert res["urgency_pulse"][0]["is_new"] is True

@pytest.mark.asyncio
async def test_urgency_pulse_no_change():
    ctx = _MockCtx()
    now = time.time()
    ctx.urgency_index = {
        "s1": {"value": "Fix bug", "deadline_ts": now + 5 * 3600, "expired": False}
    }
    
    await ctx_active(ctx)  # First call populates cache
    res = await ctx_active(ctx)  # Second call
    assert "urgency_pulse" not in res

@pytest.mark.asyncio
async def test_urgency_pulse_escalation():
    ctx = _MockCtx()
    now = time.time()
    
    # First call: medium (48h left)
    ctx.urgency_index = {
        "s1": {"value": "Task", "deadline_ts": now + 48 * 3600, "expired": False}
    }
    await ctx_active(ctx)
    assert ctx.urgency_level_cache["s1"] == "medium"
    
    # Second call: escalation to critical (5h left)
    ctx.urgency_index["s1"]["deadline_ts"] = now + 5 * 3600
    res = await ctx_active(ctx)
    
    assert "urgency_pulse" in res
    assert res["urgency_pulse"][0]["level"] == "critical"
    assert res["urgency_pulse"][0]["prev_level"] == "medium"
    assert res["urgency_pulse"][0]["is_new"] is False

@pytest.mark.asyncio
async def test_urgency_pulse_expired_skipped():
    ctx = _MockCtx()
    now = time.time()
    ctx.urgency_index = {
        "s1": {"value": "Done", "deadline_ts": now + 1 * 3600, "expired": True}
    }
    
    res = await ctx_active(ctx)
    assert "urgency_pulse" not in res
    assert "s1" not in ctx.urgency_level_cache

@pytest.mark.asyncio
async def test_urgency_level_cache_cleanup():
    ctx = _MockCtx()
    now = time.time()
    ctx.urgency_index = {"s1": {"value": "T1", "deadline_ts": now + 5, "expired": False}}
    
    await ctx_active(ctx)
    assert "s1" in ctx.urgency_level_cache
    
    ctx.urgency_index = {} # s1 evicted from urgency_index
    await ctx_active(ctx)
    assert "s1" not in ctx.urgency_level_cache

# --- Tests for Phase 11.G (Session Closure Trigger) ---

def test_farewell_detection():
    # EN
    assert _is_farewell("goodbye") is True
    assert _is_farewell("that's all for today") is True
    assert _is_farewell("wrapping up") is True
    # RU
    assert _is_farewell("пока") is True
    assert _is_farewell("на сегодня всё") is True
    assert _is_farewell("спасибо за работу") is True
    # False positives
    assert _is_farewell("bye") is False # length < 4
    assert _is_farewell("ok") is False
    assert _is_farewell("let's continue") is False

@pytest.mark.asyncio
async def test_closure_fires_on_farewell_en():
    ctx = _MockCtx()
    ctx.last_message_text = "That's all for today, thanks!"
    
    with patch("mnemostroma.tools.read._ctx_bridge", new_callable=AsyncMock) as mock_bridge:
        mock_bridge.return_value = {"mock": "bridge"}
        res = await ctx_active(ctx)
        
        assert "session_closure" in res
        assert res["session_closure"]["trigger"] == "farewell_detected"
        assert res["session_closure"]["bridge"] == {"mock": "bridge"}
        assert ctx.closure_cooldown_until > time.time()

@pytest.mark.asyncio
async def test_closure_fires_on_farewell_ru():
    ctx = _MockCtx()
    ctx.last_message_text = "Ладно, на этом всё. До завтра!"
    
    with patch("mnemostroma.tools.read._ctx_bridge", new_callable=AsyncMock) as mock_bridge:
        mock_bridge.return_value = {"mock": "bridge"}
        res = await ctx_active(ctx)
        
        assert "session_closure" in res
        assert res["session_closure"]["trigger"] == "farewell_detected"

@pytest.mark.asyncio
async def test_closure_absent_on_normal_message():
    ctx = _MockCtx()
    ctx.last_message_text = "Can we refactor the observer pipeline?"
    
    res = await ctx_active(ctx)
    assert "session_closure" not in res

@pytest.mark.asyncio
async def test_closure_respects_cooldown():
    ctx = _MockCtx()
    ctx.last_message_text = "Good night"
    ctx.closure_cooldown_until = time.time() + 1000
    
    res = await ctx_active(ctx)
    assert "session_closure" not in res

@pytest.mark.asyncio
async def test_closure_disabled_via_config():
    ctx = _MockCtx()
    ctx.config.session_closure.enabled = False
    ctx.last_message_text = "Goodbye"
    
    res = await ctx_active(ctx)
    assert "session_closure" not in res

@pytest.mark.asyncio
async def test_closure_bridge_structure():
    # This test actually calls the real ctx_bridge (mocked here but structure check)
    ctx = _MockCtx()
    ctx.last_message_text = "End session"
    
    # We need a bit more in ctx for real ctx_bridge to work if not mocked
    # but the instruction says "mock SystemContext", so we keep it simple.
    with patch("mnemostroma.tools.read._ctx_bridge", new_callable=AsyncMock) as mock_bridge:
        mock_bridge.return_value = {
            "intent_summary": "...",
            "active_variables": [],
            "last_decisions": [],
            "open_issues": [],
            "urgency_active": [],
            "ram_sessions": 0
        }
        res = await ctx_active(ctx)
        assert "session_closure" in res
        bridge = res["session_closure"]["bridge"]
        assert "intent_summary" in bridge
        assert "active_variables" in bridge
