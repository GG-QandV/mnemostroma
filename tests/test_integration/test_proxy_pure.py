import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from mnemostroma.integration.proxy import ConductorProxy

@pytest.mark.asyncio
async def test_pure_mode_no_tools():
    # Setup mock context with pure_context = True
    ctx = MagicMock()
    ctx.config.integration.pure_context = True
    ctx.config.tools.enabled = True
    ctx.ram_index = {}
    ctx.urgency_index = {}
    ctx.experience_index = None
    
    proxy = ConductorProxy(ctx)
    
    with patch("mnemostroma.integration.proxy.ctx_semantic", new_callable=AsyncMock, return_value=[]):
        block = await proxy.inject("test query")
        # In pure mode, tools MUST be empty regardless of tools.enabled
        assert block.tools == []
        assert "memory_context" in block.context

@pytest.mark.asyncio
async def test_tools_disabled_no_tools():
    # Setup mock context with pure_context = False but tools.enabled = False
    ctx = MagicMock()
    ctx.config.integration.pure_context = False
    ctx.config.tools.enabled = False
    ctx.ram_index = {}
    ctx.urgency_index = {}
    ctx.experience_index = None
    
    proxy = ConductorProxy(ctx)
    
    with patch("mnemostroma.integration.proxy.ctx_semantic", new_callable=AsyncMock, return_value=[]):
        block = await proxy.inject("test query")
        # When tools are disabled in config, tools MUST be empty
        assert block.tools == []
        assert "memory_context" in block.context

@pytest.mark.asyncio
async def test_normal_mode_has_tools():
    # Setup mock context with pure_context = False and tools.enabled = True
    ctx = MagicMock()
    ctx.config.integration.pure_context = False
    ctx.config.tools.enabled = True
    ctx.ram_index = {}
    ctx.urgency_index = {}
    ctx.experience_index = None
    
    proxy = ConductorProxy(ctx)
    
    with patch("mnemostroma.integration.proxy.ctx_semantic", new_callable=AsyncMock, return_value=[]):
        block = await proxy.inject("test query")
        # In normal mode, tools should be present
        assert len(block.tools) > 0
        assert any(t["name"] == "ctx_semantic" for t in block.tools)
