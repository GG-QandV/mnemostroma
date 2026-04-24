# SPDX-License-Identifier: FSL-1.1-MIT
"""Regression tests for v1.8.4 fixes: urgency persistence, Rule 2, and critical protection."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import os
import psutil

from mnemostroma.memory.dissolver import Dissolver, can_evict
from mnemostroma.memory.consolidation import ConsolidationWorker
from mnemostroma.memory.session_index import SessionBrief

def _make_sb(session_id, importance="important", deadline_ts=None):
    sb = SessionBrief(
        session_id=session_id,
        brief=f"brief-{session_id}",
        tags=["test"],
        importance=importance,
        score=0.5,
        resolution=1.0,
        created_at=int(time.time()),
    )
    if deadline_ts is not None:
        sb.deadline_ts = deadline_ts
        sb.urgency_expired = False
    return sb

class _MockCtx:
    def __init__(self):
        self.ram_index = {}
        self.config = MagicMock()
        self.persistence = AsyncMock()
        self.models = MagicMock()
        self.models.embedder = None
        self.config.resources.session_window_size = 400
        self.config.resources.ram_soft_limit_mb = 520
        self.config.resources.ram_hard_limit_mb = 600
        self.config.dissolver.consolidation_interval_sec = 300
        self.config.observer.anchor_stoplist = []
        self.config.experience.layer_enabled = False
        self.config.anchor_decay.enabled = False
        self.config.feedback.recalibration_enabled = False
        self.log_writer = AsyncMock()
        self.pending_emotions = []
        self.conflict_warnings = []
        self.surfaced_queue = []
        self.open_loops_queue = []
        self.onnx_baseline_ready = False
        self.onnx_baseline_mb = 0.0

@pytest.mark.asyncio
async def test_urgency_expiry_persists_to_db():
    """T1: Urgency-expired session must be saved to persistence with correct flags."""
    ctx = _MockCtx()
    # Create session with expired deadline
    sid = "expired-1"
    sb = _make_sb(sid, deadline_ts=int(time.time()) - 3600)
    sb.urgency_active = True
    ctx.ram_index[sid] = sb
    
    # Mock persistence.get_session_by_id to return the "updated" version for assertion check
    ctx.persistence.get_session_by_id.return_value = sb

    worker = ConsolidationWorker(ctx)
    await worker.consolidate()
    
    # Verify flags updated in RAM
    assert sb.urgency_active is False
    assert sb.urgency_expired is True
    
    # Verify persistence calls
    ctx.persistence.enqueue_session.assert_called()
    ctx.persistence.flush.assert_called()
    ctx.persistence.get_session_by_id.assert_called_with(sid)

@pytest.mark.asyncio
async def test_no_evict_loop_within_window():
    """T2: No eviction should occur if count < window * 0.8 and RAM < soft_limit."""
    ctx = _MockCtx()
    ctx.config.resources.session_window_size = 400
    # Add 318 sessions
    for i in range(318):
        ctx.ram_index[f"s{i}"] = _make_sb(f"s{i}")
        
    dissolver = Dissolver(ctx)
    with patch('psutil.Process') as mock_proc:
        # Mock RAM at 470 MB (below 520 soft limit)
        mock_proc.return_value.memory_info.return_value.rss = 470 * 1024 * 1024
        
        # Capture eviction calls
        with patch.object(dissolver, 'evict_n_oldest', AsyncMock()) as mock_evict:
            await dissolver.check_and_evict()
            mock_evict.assert_not_called()

@pytest.mark.asyncio
async def test_rule2_triggers_on_ram_overflow():
    """T3: Rule 2 should trigger 10% eviction if RAM > soft_limit even if count < window."""
    ctx = _MockCtx()
    ctx.config.resources.session_window_size = 1000
    ctx.config.resources.ram_soft_limit_mb = 500
    ctx.onnx_baseline_ready = True
    ctx.onnx_baseline_mb = 0.0
    # Add 100 sessions
    for i in range(100):
        ctx.ram_index[f"s{i}"] = _make_sb(f"s{i}")
        
    dissolver = Dissolver(ctx)
    with patch('psutil.Process') as mock_proc:
        # Mock RAM at 530 MB (above 500 soft limit)
        mock_proc.return_value.memory_info.return_value.rss = 530 * 1024 * 1024
        
        with patch.object(dissolver, 'evict_n_oldest', AsyncMock()) as mock_evict:
            await dissolver.check_and_evict()
            # 10% of 100 is 10
            mock_evict.assert_called_once_with(10)

def test_can_evict_critical_protection():
    """T4: Critical sessions should only be evictable if RAM > 90% of hard limit."""
    ctx = _MockCtx()
    ctx.config.resources.ram_hard_limit_mb = 600
    
    sb = _make_sb("crit", importance="critical")
    
    with patch('psutil.Process') as mock_proc:
        # Case 1: RAM at 500 MB (below 540 = 600 * 0.9)
        mock_proc.return_value.memory_info.return_value.rss = 500 * 1024 * 1024
        assert can_evict(sb, ctx) is False
        
@pytest.mark.asyncio
async def test_anchor_stoplist_blocks_creation():
    """T5: Phrases in anchor_stoplist should not create any MarkerResult (discard)."""
    from mnemostroma.observer.marker import marker, MarkerAction
    from mnemostroma.observer.entities import SourceType
    
    ctx = _MockCtx()
    ctx.config.observer.anchor_stoplist = ["проверю изменения и коммитю"]
    
    # 1. Blocked phrase
    res = await marker("проверю изменения и коммитю", SourceType.AGENT, "s1", ctx)
    assert res.action == MarkerAction.DISCARD
    
    # 2. Allowed phrase
    res = await marker("some useful information", SourceType.AGENT, "s1", ctx)
    # Since we have no models in MockCtx, it should fallback to FACT
    assert res.action == MarkerAction.CREATE_ENTITY
