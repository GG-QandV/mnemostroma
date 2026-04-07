# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import asyncio
import time
import numpy as np
from pathlib import Path
from mnemostroma.core import SystemContext, Config
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.tools.read import ctx_get, ctx_semantic, ctx_active
from mnemostroma.tools.write import ctx_urgent, ctx_expire, save_content

@pytest.fixture
def mock_ctx(mocker):
    # Try to load real config or mock it
    try:
        config = Config.load(Path(__file__).parent.parent / "config.json")
    except Exception:
        # Fallback to direct init with dummy data if needed
        # But project has config.json, so this should work
        mocker.patch("mnemostroma.config.Config")
        config = mocker.Mock()
        
    ctx = SystemContext(config=config)
    ctx.log_writer = mocker.Mock()
    ctx.log_writer.log = mocker.AsyncMock()
    return ctx

@pytest.mark.asyncio
async def test_ctx_get(mock_ctx):
    # Setup RAM
    sb = SessionBrief(
        session_id="s1", brief="test", tags=[], importance="important",
        score=0.8, resolution=1.0, created_at=int(time.time())
    )
    mock_ctx.ram_index["s1"] = sb
    
    res = await ctx_get("s1", mock_ctx)
    assert res == sb
    
    res = await ctx_get("missing", mock_ctx)
    assert res is None

@pytest.mark.asyncio
async def test_ctx_active(mock_ctx):
    sb = SessionBrief(
        session_id="s1", brief="Latest Intent", tags=[], importance="critical",
        score=0.9, resolution=1.0, created_at=int(time.time())
    )
    mock_ctx.ram_index["s1"] = sb
    
    # Add urgency
    mock_ctx.urgency_index["s1"] = {
        "session_id": "s1", "value": "Deadline", "expired": False, "deadline_ts": int(time.time()) + 3600
    }
    
    res = await ctx_active(mock_ctx)
    assert res["intent_summary"] == "Latest Intent"
    assert len(res["active_variables"]) == 1
    assert len(res["urgency_active"]) == 1
    assert res["urgency_active"][0]["session_id"] == "s1"

@pytest.mark.asyncio
async def test_ctx_urgent_expire(mock_ctx):
    now = time.time()
    mock_ctx.urgency_index["s1"] = {
        "session_id": "s1", "value": "Urgent", "expired": False, "deadline_ts": int(now) + 3600
    }
    
    # Test urgent tool
    urgent_items = await ctx_urgent(mock_ctx, hours_ahead=2.0)
    assert len(urgent_items) == 1
    
    # Test expire tool
    await ctx_expire("s1", mock_ctx)
    assert mock_ctx.urgency_index["s1"]["expired"] is True
    
    urgent_items = await ctx_urgent(mock_ctx)
    assert len(urgent_items) == 0
