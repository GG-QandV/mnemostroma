# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import asyncio
import time
import numpy as np
from mnemostroma.observer.filter import deterministic_filter, detect_urgency, detect_principle
from mnemostroma.observer.pipeline import compress_text, calculate_score

def test_deterministic_filter():
    # 1. Critical
    res = deterministic_filter("We decided to use SQLite WAL.")
    assert res["importance"] == "critical"
    assert res["needs_ner"] is True # No precision items yet
    
    # 2. Principle
    res = deterministic_filter("Always remember: we never use torch.")
    assert res["importance"] == "principle"
    
    # 3. Precision
    res = deterministic_filter("Project site: https://mnemostroma.ai")
    # Matches both 'link' and 'path' patterns
    assert len(res["precision_items"]) == 2
    types = {i["type"] for i in res["precision_items"]}
    assert "link" in types
    assert "path" in types

    # 4. Urgency
    res = deterministic_filter("Need to do this tomorrow.")
    assert res["urgency"] == "deadline_d"

def test_detect_urgency():
    level, ts = detect_urgency("Deadline 2026-03-30")
    assert level == "deadline_d"
    assert isinstance(ts, int)
    
    level, ts = detect_urgency("asap")
    assert level == "deadline_h"
    assert isinstance(ts, int)
    
    level, ts = detect_urgency("Urgent, within an hour!")
    assert level == "deadline_h"
    assert isinstance(ts, int)

def test_compress_text():
    text = "Ivan Kovalenko chose PostgreSQL. This is the second sentence."
    entities = [
        {"type": "person", "value": "Ivan Kovalenko", "score": 0.99},
        {"type": "technology", "value": "PostgreSQL", "score": 0.95},
        {"type": "technology", "value": "postgresql", "score": 0.80}, # Duplicate
        {"type": "organization", "value": "Yandex", "score": 0.45}, # Under threshold
    ]
    brief, tags = compress_text(text, entities)
    
    # 1. Brief logic
    assert brief == "Ivan Kovalenko chose PostgreSQL"
    
    # 2. Tags: prefix, deduplication, threshold
    assert "per:Ivan Kovalenko" in tags
    assert "tech:PostgreSQL" in tags
    assert "tech:postgresql" not in tags # Deduplicated
    assert "org:Yandex" not in tags # Low score
    assert len(tags) == 2

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
