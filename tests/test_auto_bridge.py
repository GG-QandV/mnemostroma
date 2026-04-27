# SPDX-License-Identifier: FSL-1.1-MIT
"""Unit tests for AutoBridgeWorker."""

import time
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from mnemostroma.subconscious.dreamer import AutoBridgeWorker

def test_coverage_score_perfect():
    worker = AutoBridgeWorker(MagicMock(), MagicMock())
    anchors = ["[task] fix bug", "[decision] use sqlite"]
    bridge_text = "Summary of work. [task] fix bug and [decision] use sqlite."
    assert worker._compute_coverage(bridge_text, anchors) == 1.0

def test_coverage_score_partial():
    worker = AutoBridgeWorker(MagicMock(), MagicMock())
    anchors = ["[task] fix bug", "[decision] use sqlite"]
    bridge_text = "Summary of work. [task] fix bug only."
    # 1 hit out of 2 anchors = 0.5
    assert worker._compute_coverage(bridge_text, anchors) == 0.5

def test_coverage_score_empty_anchors():
    worker = AutoBridgeWorker(MagicMock(), MagicMock())
    assert worker._compute_coverage("Any text", []) == 1.0

def test_cooldown_guard():
    with patch("mnemostroma.subconscious.dreamer.AutoBridgeWorker._get_active_session_id") as mock_get_sid, \
         patch("time.time") as mock_time:
        ctx = MagicMock()
        worker = AutoBridgeWorker(MagicMock(), ctx)
        session_id = "test_session"
        mock_get_sid.return_value = session_id
        mock_time.return_value = 2000.0
        
        # 1. First run - should proceed (last_bridge is empty)
        with patch.object(worker, "_generate_bridge", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = "Bridge text"
            ctx.ram_index = {session_id: MagicMock()}
            worker._collect_session_anchors = MagicMock(return_value=[])
            
            with patch("mnemostroma.storage.log_writer.log_event", new_callable=AsyncMock):
                asyncio.run(worker._try_bridge())
                assert mock_gen.call_count == 1
                
                # 2. Second run - within cooldown (2000.0 + 1)
                mock_time.return_value = 2001.0
                asyncio.run(worker._try_bridge())
                assert mock_gen.call_count == 1 # still 1

def test_empty_session_id():
    with patch("mnemostroma.subconscious.dreamer.AutoBridgeWorker._get_active_session_id") as mock_get_sid:
        worker = AutoBridgeWorker(MagicMock(), MagicMock())
        mock_get_sid.return_value = None
        
        with patch.object(worker, "_generate_bridge", new_callable=AsyncMock) as mock_gen:
            asyncio.run(worker._try_bridge())
            assert mock_gen.call_count == 0
