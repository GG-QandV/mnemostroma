# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for PROTOCOL_BLOCK injection in ConductorProxy."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from mnemostroma.integration.proxy import ConductorProxy
from mnemostroma.memory.session_index import SessionBrief

class _MockCtx:
    def __init__(self):
        self.ram_index = {}
        self.urgency_index = {}
        self.config = MagicMock()
        self.config.integration.pure_context = False
        self.config.experience.layer_enabled = False
        self.config.tools.enabled = True
        self.config.search.embedding_dim = 384
        self.log_writer = AsyncMock()
        self._last_injected_ids = []

def make_proxy(with_principles=False, with_decisions=False):
    ctx = _MockCtx()
    if with_principles:
        sb = SessionBrief("p1", "Principle 1", ["p"], "principle", 1.0, 1.0, int(time.time()))
        ctx.ram_index["p1"] = sb
    if with_decisions:
        sb = SessionBrief("d1", "Decision 1", ["d"], "critical", 0.9, 1.0, int(time.time()))
        ctx.ram_index["d1"] = sb
    return ConductorProxy(ctx)

@pytest.mark.asyncio
async def test_protocol_block_always_injected():
    """T1: PROTOCOL_BLOCK должен быть в каждом вызове inject, без исключений."""
    proxy = make_proxy()
    with patch("mnemostroma.integration.proxy.ctx_semantic", AsyncMock(return_value=[])):
        # Первый запрос
        result1 = await proxy.inject("привет")
        assert "<agent_protocol>" in result1.context
        
        # Середина сессии
        for _ in range(5):
            await proxy.inject("продолжаем работу")
        result2 = await proxy.inject("что дальше?")
        assert "<agent_protocol>" in result2.context
        
        # После очистки кэша
        proxy._static_cache = ""
        result3 = await proxy.inject("новая сессия")
        assert "<agent_protocol>" in result3.context

@pytest.mark.asyncio
async def test_protocol_block_is_first():
    """T2: PROTOCOL_BLOCK должен быть до principles и decisions в блоке."""
    proxy = make_proxy(with_principles=True, with_decisions=True)
    with patch("mnemostroma.integration.proxy.ctx_semantic", AsyncMock(return_value=[])):
        result = await proxy.inject("любой запрос")
        ctx_str = result.context
        
        proto_pos = ctx_str.index("<agent_protocol>")
        principle_pos = ctx_str.index("<principles>")
        decision_pos = ctx_str.index("<decisions>")
        
        assert proto_pos < principle_pos
        assert proto_pos < decision_pos

@pytest.mark.asyncio
async def test_protocol_block_content_intact():
    """T3: Все обязательные директивы должны присутствовать дословно."""
    proxy = make_proxy()
    with patch("mnemostroma.integration.proxy.ctx_semantic", AsyncMock(return_value=[])):
        result = await proxy.inject("тест")
        ctx_str = result.context
        
        assert "ctx_semantic" in ctx_str
        assert "ctx_anchors" in ctx_str
        assert "ctx_search" in ctx_str
        assert "ctx_bridge()" in ctx_str
        assert "MANDATORY" in ctx_str
        assert "FORBIDDEN" in ctx_str
        assert "Reading is not optional" in ctx_str

@pytest.mark.asyncio
async def test_protocol_block_no_duplicates():
    """T4: PROTOCOL_BLOCK не должен появляться дважды в одном инжекте."""
    proxy = make_proxy()
    with patch("mnemostroma.integration.proxy.ctx_semantic", AsyncMock(return_value=[])):
        result = await proxy.inject("тест")
        ctx_str = result.context
        
        assert ctx_str.count("<agent_protocol>") == 1
        assert ctx_str.count("</agent_protocol>") == 1

@pytest.mark.asyncio
async def test_protocol_block_within_token_budget():
    """T5: Итоговый инжект с протоколом должен укладываться в 600 токенов."""
    proxy = make_proxy(with_principles=True, with_decisions=True)
    # Mock semantic with several results
    results = [SessionBrief(f"s{i}", "A"*100, ["t"], "important", 0.5, 1.0, int(time.time())) for i in range(3)]
    with patch("mnemostroma.integration.proxy.ctx_semantic", AsyncMock(return_value=results)):
        result = await proxy.inject("тест с полным контекстом")
        ctx_str = result.context
        
        # ~4 символа на токен — грубая оценка
        estimated_tokens = len(ctx_str) / 4
        assert estimated_tokens <= 600, f"Превышен бюджет: ~{estimated_tokens:.0f} токенов"
