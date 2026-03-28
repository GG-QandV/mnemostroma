# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import asyncio
import time
import numpy as np
from mnemostroma.observer.filter import deterministic_filter, detect_urgency, detect_principle
from mnemostroma.observer.pipeline import compress_text, calculate_score

def test_deterministic_filter():
    # 1. Critical
    res = deterministic_filter("Мы решили использовать SQLite WAL.")
    assert res["importance"] == "critical"
    assert res["needs_ner"] is True # No precision items yet
    
    # 2. Principle
    res = deterministic_filter("Всегда запомни: мы никогда не используем torch.")
    assert res["importance"] == "principle"
    
    # 3. Precision
    res = deterministic_filter("Сайт проекта: https://mnemostroma.ai")
    assert len(res["precision_items"]) == 1
    assert res["precision_items"][0]["type"] == "link"

    # 4. Urgency
    res = deterministic_filter("Нужно сделать это завтра.")
    assert res["urgency"] == "deadline_d"

def test_detect_urgency():
    level, ts = detect_urgency("Дедлайн 2026-03-30")
    assert level == "deadline_d"
    assert isinstance(ts, int)
    
    level, ts = detect_urgency("asap")
    assert level == "deadline_h"
    assert isinstance(ts, int)
    
    level, ts = detect_urgency("Срочно, в течение часа!")
    assert level == "deadline_h"
    assert isinstance(ts, int)

def test_compress_text():
    text = "Это первое предложение. Это второе предложение."
    brief, tags = compress_text(text, [{"value": "тест", "score": 0.9}])
    assert brief == "Это первое предложение"
    assert "тест" in tags

@pytest.mark.asyncio
async def test_calculate_score(mocker):
    # Mocking SystemContext for score calculation
    ctx = mocker.Mock()
    ctx.config.score.temporal_decay_lambda = 0.05
    ctx.config.score.weight_relevance = 0.5
    ctx.config.score.weight_temporal = 0.3
    ctx.config.score.weight_importance = 0.2
    ctx.config.importance.weight_critical = 1.0
    
    score = await calculate_score(relevance=1.0, created_at=int(time.time()), importance="critical", ctx=ctx)
    # Score should be near 0.5*1.0 + 0.3*1.0 + 0.2*1.0 = 1.0
    assert 0.9 < score <= 1.0
