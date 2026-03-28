# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime
import time

from mnemostroma.integration.proxy import ConductorProxy
from mnemostroma.core import SystemContext

@pytest.fixture
def mock_ctx():
    # Mock just enough SystemContext to test proxy cache
    ctx = MagicMock(spec=SystemContext)
    ctx.ram_index = {}
    ctx.urgency_index = {}
    return ctx

@pytest.mark.asyncio
async def test_proxy_inject_first_session(mock_ctx):
    proxy = ConductorProxy(mock_ctx)
    
    # When memory is empty, semantic should return []
    with patch("mnemostroma.integration.proxy.ctx_semantic", return_value=[]) as mock_sem:
        block = await proxy.inject("Hello there")
        
        assert "First session. Memory is empty" in block.context
        assert "<memory_context updated=" in block.context
        assert len(block.tools) == 9
        assert block.stats["cached"] is False

@pytest.mark.asyncio
async def test_proxy_inject_with_data(mock_ctx):
    proxy = ConductorProxy(mock_ctx)
    
    # Mock RAM index with decisions and principles
    mock_sb_1 = MagicMock()
    mock_sb_1.session_id = "s1"
    mock_sb_1.brief = "Keep tokens secure"
    mock_sb_1.importance = "principle"
    mock_sb_1.conflict_flag = False
    mock_sb_1.created_at = time.time() - 100
    
    mock_sb_2 = MagicMock()
    mock_sb_2.session_id = "s2"
    mock_sb_2.brief = "Use PostgreSQL"
    mock_sb_2.importance = "critical"
    mock_sb_2.conflict_flag = True
    mock_sb_2.created_at = time.time()
    
    mock_ctx.ram_index = {"s1": mock_sb_1, "s2": mock_sb_2}
    
    # Mock deadlines
    mock_ctx.urgency_index = {
        "u1": {
            "title": "Release v1",
            "deadline_ts": time.time() + 86400,
            "expired": False
        }
    }
    
    # Mock semantic search returning relevant sessions
    mock_sb_rel = MagicMock()
    mock_sb_rel.session_id = "s3"
    mock_sb_rel.brief = "Discussed JWT vs cookies"
    
    with patch("mnemostroma.integration.proxy.ctx_semantic", return_value=[mock_sb_rel]):
        block = await proxy.inject("What database?")
        
        # Check XML tags are present
        assert "<decisions>" in block.context
        assert "- Use PostgreSQL" in block.context
        
        assert "<principles>" in block.context
        assert "- Keep tokens secure" in block.context
        
        assert "<conflicts>" in block.context
        assert "- Use PostgreSQL" in block.context
        
        assert "<deadlines>" in block.context
        assert "Release v1" in block.context
        
        assert "<last_session>" in block.context
        
        assert "<relevant>" in block.context
        assert "- s3: Discussed JWT vs cookies" in block.context
        
        # Second call should hit the static cache
        block2 = await proxy.inject("Another query")
        assert block2.stats["cached"] is True
