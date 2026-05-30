# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import numpy as np
from mnemostroma.observer.session_classifier import classify_session_type

from unittest.mock import MagicMock, AsyncMock
from mnemostroma.observer.steps.base import IOEvent, PipelineContext
from mnemostroma.observer.steps.persist_step import PersistStep

def test_classify_code_returns_content():
    text = "Here is a code snippet:\ndef my_function():\n    return True\nclass UserRepo:\n    pass"
    assert classify_session_type(text) == "content"

def test_classify_research_returns_research():
    text = "We need to analyze the current article and perform a benchmark study on the metrics."
    assert classify_session_type(text) == "research"

def test_classify_context_returns_context():
    text = "Let's discuss the next steps and set a deadline for the milestone. Any blockers?"
    assert classify_session_type(text) == "context"

def test_classify_below_threshold_returns_none():
    # Only one keyword "discuss" - should be below threshold _MIN_SCORE=2
    text = "Let's discuss this."
    assert classify_session_type(text) is None

def test_classify_empty_returns_none():
    assert classify_session_type("") is None

@pytest.mark.asyncio
async def test_persist_step_routes_to_content_manager():
    # 1. Mock SystemContext and ContentManager
    ctx = MagicMock()
    ctx.content = AsyncMock()
    ctx.persistence = MagicMock()
    ctx.persistence.save_anchor = AsyncMock()
    
    # 2. Mock config
    ctx.config.session_type_classify_after_n = 5
    ctx.config.observer.tags_max_per_session = 5
    ctx.config.search.pipeline_width = 1
    ctx.config.precision_guard.ram_cap = 100
    ctx.config.precision_guard.enabled = True
    ctx.session_index = None
    
    # 3. Create IOEvent and PipelineContext
    text = "def my_function():\n    class User:\n        pass"
    event = IOEvent(text=text, session_id="test_sess")
    pctx = PipelineContext(event=event, ctx=ctx)
    pctx.mark_result = None
    pctx.metadata = {
        "msg_count": 5,
        "stripped": text,
        "created_at": 123456789,
        "embedding_f32": np.zeros(384, dtype=np.float32)
    }
    pctx.importance = "important"
    pctx.entities = [{"type": "technology", "value": "auth_middleware"}]
    
    # 4. Run PersistStep
    # This should trigger classification and call ctx.content.save
    await PersistStep().run(pctx)
    
    # 5. Assertions
    # Note: This will fail until Sonnet implements the integration
    assert pctx.session_type == "content"
    assert pctx.sb.session_type == "content"
    ctx.content.save.assert_called_once()
