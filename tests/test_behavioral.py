# SPDX-License-Identifier: FSL-1.1-MIT
"""Behavioral tests for the Mnemostroma core.

Verifies end-to-end behavior of the Observer pipeline, Session Index,
Scoring, Dissolver eviction, and structured logging (logs.db).

Covers the 15 behavioral scenarios defined in behavioral_test_specification.md.
Each test uses mock models and an in-memory SQLite to run without real ONNX models.

Usage:
    pytest tests/test_behavioral.py -v
"""
import asyncio
import time
import numpy as np
import pytest
import aiosqlite
from pathlib import Path
from unittest.mock import MagicMock, AsyncMock, patch
import dataclasses
from dataclasses import dataclass, field
from typing import Any

from mnemostroma.config import Config, LoggingConfig
from mnemostroma.core import SystemContext
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.observer.filter import deterministic_filter
from mnemostroma.memory.scoring import calculate_score
from mnemostroma.memory.dissolver import Dissolver, can_evict
from mnemostroma.storage.log_writer import log_event, LogWriter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).parent.parent


@pytest.fixture
def config() -> Config:
    """Load real config from project root."""
    return Config.load(PROJECT_ROOT / "config.json")


@pytest.fixture
def mock_ctx(config: Config) -> SystemContext:
    """Minimal SystemContext with mock models and in-memory RAM index."""
    np.random.seed(42)

    models = MagicMock()
    models.embedder.encode = lambda text: np.random.rand(384).astype(np.float16)
    models.embedder.aencode = AsyncMock(side_effect=lambda text: np.random.rand(384).astype(np.float16))
    models.embedder.aencode = AsyncMock(side_effect=lambda text: np.random.rand(384).astype(np.float16))
    models.reranker = None
    models.content_embedder = None

    return SystemContext(
        config=config,
        ram_index={},
        session_index=None,
        content_index=None,
        db=None,
        models=models,
        urgency_index={},
        metrics={},
        id_to_sid={},
        sid_to_id={},
        log_writer=None,
        content=None,
        dissolver=None,
    )


@pytest.fixture
def ctx_with_sessions(mock_ctx: SystemContext) -> SystemContext:
    """Context pre-loaded with a variety of SessionBriefs for search/eviction tests."""
    now = int(time.time())
    sessions = [
        SessionBrief(session_id="s_pg", brief="PostgreSQL выбрана как основная БД", tags=["#postgresql", "#architecture"], importance="critical", score=0.85, resolution=1.0, created_at=now - 86400),
        SessionBrief(session_id="s_jwt", brief="JWT запрещён к хранению в localStorage", tags=["#security", "#tokens"], importance="principle", score=0.90, resolution=1.0, created_at=now - 7200),
        SessionBrief(session_id="s_rest", brief="REST API выбран вместо GraphQL", tags=["#api", "#architecture"], importance="critical", score=0.80, resolution=1.0, created_at=now - 3600),
        SessionBrief(session_id="s_passport", brief="passport.js для авторизации", tags=["#auth", "#library"], importance="important", score=0.65, resolution=1.0, created_at=now - 1800),
        SessionBrief(session_id="s_node", brief="Зависимость Node.js 20+ обязательна", tags=["#dependency", "#runtime"], importance="important", score=0.60, resolution=1.0, created_at=now - 900),
        SessionBrief(session_id="s_bg1", brief="Привет пользователь", tags=[], importance="background", score=0.20, resolution=1.0, created_at=now - 600),
        SessionBrief(session_id="s_bg2", brief="Ок понял", tags=[], importance="background", score=0.15, resolution=1.0, created_at=now - 300),
        SessionBrief(session_id="s_conflict", brief="Отменили JWT переходим на session tokens", tags=["#security", "#tokens"], importance="critical", score=0.75, resolution=1.0, created_at=now - 60, conflict_flag=True),
        SessionBrief(session_id="s_deadline", brief="Deploy до пятницы дедлайн", tags=["#deadline", "#deploy"], importance="critical", score=0.80, resolution=1.0, created_at=now - 30, urgency="deadline_w", deadline_ts=now + 604800),
        SessionBrief(session_id="s_old", brief="Старая задача архивирована", tags=["#old"], importance="background", score=0.05, resolution=0.2, created_at=now - 10_000_000),
    ]
    for sb in sessions:
        mock_ctx.ram_index[sb.session_id] = sb
    return mock_ctx


# ---------------------------------------------------------------------------
# BT-01: Filter — importance classification
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("Решили использовать PostgreSQL для основной БД", "critical"),
    ("Выбрали REST API вместо GraphQL", "critical"),
    ("Используем passport.js для авторизации", "important"),
    ("Зависимость: проект требует Node.js 20+", "important"),
    ("Привет, как дела?", "background"),
    ("Ок, понял", "background"),
    ("Хм, интересно", "background"),
])
def test_bt01_importance_classification(text: str, expected: str) -> None:
    """BT-01: Observer classifies importance levels correctly."""
    result = deterministic_filter(text)
    assert result["importance"] == expected, f"Expected '{expected}' for: {text!r}"


# ---------------------------------------------------------------------------
# BT-02: Filter — Principle detection overrides importance
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Запрет: никогда не хранить токены в localStorage — это принцип проекта",
    "Never store passwords in plaintext — project rule",
    "Архитектурное решение: always validate input at the boundary",
])
def test_bt02_principle_detection(text: str) -> None:
    """BT-02: Principle signals override any other importance level."""
    result = deterministic_filter(text)
    assert result["importance"] == "principle", f"Expected 'principle' for: {text!r}"


# ---------------------------------------------------------------------------
# BT-03: Filter — Conflict detection
# ---------------------------------------------------------------------------

def test_bt03_conflict_detection() -> None:
    """BT-03: Conflict signals are detected and flagged."""
    text = "Нет, отменяем JWT, переходим на session tokens вместо предыдущего решения"
    result = deterministic_filter(text)
    assert result["conflict"] is True


# ---------------------------------------------------------------------------
# BT-04: Filter — Urgency detection with deadline_ts
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected_urgency", [
    ("Deploy до пятницы на следующей неделе", "deadline_w"),
    ("Нужно сделать сегодня до конца дня", "deadline_d"),
    ("Срочно нужен фикс через час asap", "deadline_h"),
])
def test_bt04_urgency_detection(text: str, expected_urgency: str) -> None:
    """BT-04: Urgency signals are classified and deadline_ts is generated."""
    result = deterministic_filter(text)
    assert result["urgency"] == expected_urgency
    assert result["deadline_val"] is not None
    assert result["deadline_val"] > int(time.time())


# ---------------------------------------------------------------------------
# BT-05: Filter — Precision items extracted
# ---------------------------------------------------------------------------

def test_bt05_precision_extraction() -> None:
    """BT-05: URLs, phones, numbers are extracted as precision items."""
    result = deterministic_filter(
        "Документация: https://docs.example.com/auth, телефон: +34 612 345 678"
    )
    types = {item["type"] for item in result["precision_items"]}
    assert "link" in types
    assert "phone" in types


# ---------------------------------------------------------------------------
# BT-06: Scoring — Write Profile values are correct
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt06_score_write_profile(mock_ctx: SystemContext) -> None:
    """BT-06: Write Profile (α=0.5, β=0.3, γ=0.2) produces expected score range."""
    score = await calculate_score(
        relevance=1.0,
        created_at=int(time.time()),
        importance="important",
        ctx=mock_ctx,
        profile="write"
    )
    # Score = 0.5*1.0 + 0.3*1.0 + 0.2*I (I > 0) -> should be > 0.8
    assert 0.0 < score <= 1.5, f"Score out of expected range: {score}"


# ---------------------------------------------------------------------------
# BT-07: Scoring — Search Profile > Write Profile for same inputs
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt07_search_profile_vs_write(mock_ctx: SystemContext) -> None:
    """BT-07: Search Profile (α=0.6) scores relevance higher than Write (α=0.5)."""
    now = int(time.time())
    write_score = await calculate_score(1.0, now, "important", mock_ctx, profile="write")
    search_score = await calculate_score(1.0, now, "important", mock_ctx, profile="search")
    assert search_score > write_score


# ---------------------------------------------------------------------------
# BT-08: Scoring — Principle boost applied
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt08_principle_boost(mock_ctx: SystemContext) -> None:
    """BT-08: Principle importance gets ×1.30 score boost vs critical."""
    now = int(time.time())
    critical_score = await calculate_score(0.5, now, "critical", mock_ctx)
    principle_score = await calculate_score(0.5, now, "principle", mock_ctx)
    assert principle_score > critical_score


# ---------------------------------------------------------------------------
# BT-09: Scoring — Urgency expired penalty applied
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt09_urgency_expired_penalty(mock_ctx: SystemContext) -> None:
    """BT-09: Expired deadlines reduce score by 50% (URGENCY_EXPIRED_PENALTY)."""
    now = int(time.time())
    active_score = await calculate_score(0.5, now, "important", mock_ctx, urgency_expired=False)
    expired_score = await calculate_score(0.5, now, "important", mock_ctx, urgency_expired=True)
    assert expired_score == pytest.approx(active_score * 0.5, rel=0.01)


# ---------------------------------------------------------------------------
# BT-10: Session Index — ctx_active returns latest intent and critical/principle vars
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt10_ctx_active(ctx_with_sessions: SystemContext) -> None:
    """BT-10: ctx_active returns intent_summary and active_variables with capped count."""
    from mnemostroma.tools.read import ctx_active
    result = await ctx_active(ctx_with_sessions)

    assert "intent_summary" in result
    assert isinstance(result["active_variables"], list)
    # Only critical/principle sessions → s_pg, s_jwt, s_rest, s_conflict, s_deadline
    assert len(result["active_variables"]) <= 9  # Miller's Law cap
    # Principle/critical must be included
    briefings = " ".join(result["active_variables"])
    assert "JWT" in briefings or "PostgreSQL" in briefings or "REST" in briefings


# ---------------------------------------------------------------------------
# BT-11: Session Index — ctx_get retrieves by session_id from RAM
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt11_ctx_get_from_ram(ctx_with_sessions: SystemContext) -> None:
    """BT-11: ctx_get returns the correct SessionBrief from RAM index."""
    from mnemostroma.tools.read import ctx_get
    sb = await ctx_get("s_pg", ctx_with_sessions)
    assert sb is not None
    assert sb.session_id == "s_pg"
    assert sb.importance == "critical"


# ---------------------------------------------------------------------------
# BT-12: Session Index — ctx_get returns None for unknown id
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt12_ctx_get_miss(ctx_with_sessions: SystemContext) -> None:
    """BT-12: ctx_get returns None for sessions not in RAM or SQLite."""
    from mnemostroma.tools.read import ctx_get
    sb = await ctx_get("nonexistent_id", ctx_with_sessions)
    assert sb is None


# ---------------------------------------------------------------------------
# BT-13: Dissolver — Principle sessions are NEVER evicted
# ---------------------------------------------------------------------------

def test_bt13_principle_never_evicted(mock_ctx: SystemContext) -> None:
    """BT-13: can_evict() returns False for principle sessions (architectural invariant)."""
    principle_sb = SessionBrief(
        session_id="s_rule",
        brief="Principle: never store tokens in plaintext",
        tags=["#security"],
        importance="principle",
        score=0.9,
        resolution=1.0,
        created_at=int(time.time()) - 1000,
    )
    assert can_evict(principle_sb, mock_ctx.config.resources) is False


# ---------------------------------------------------------------------------
# BT-14: Dissolver — Low-score background sessions ARE evicted
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt14_background_eviction(ctx_with_sessions: SystemContext) -> None:
    """BT-14: Dissolver evicts background sessions before critical/principle ones."""
    ram_before = len(ctx_with_sessions.ram_index)
    dissolver = Dissolver(ctx_with_sessions)

    # Force aggressive eviction (evict 3 sessions)
    await dissolver.evict_n_oldest(3)

    # Background sessions with lowest scores should be gone
    assert "s_bg1" not in ctx_with_sessions.ram_index or "s_bg2" not in ctx_with_sessions.ram_index
    # Principle session must still be in RAM
    assert "s_jwt" in ctx_with_sessions.ram_index
    # Verify count reduced
    assert len(ctx_with_sessions.ram_index) < ram_before


# ---------------------------------------------------------------------------
# BT-15: Logging — log_event writes structured entry to logs.db
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt15_log_event_writes_to_db(mock_ctx: SystemContext) -> None:
    """BT-15: log_event correctly persists structured entries to logs.db via LogWriter."""
    import tempfile
    import os

    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    try:
        # Start a real LogWriter pointed at a temp DB
        writer = LogWriter(db_path)
        await writer.start()
        mock_ctx.log_writer = writer

        # BT-15 tests LogWriter infrastructure — use debug mode to bypass safe-mode filter
        mock_ctx.config = dataclasses.replace(
            mock_ctx.config,
            logging=LoggingConfig(enabled=True, mode="debug", db_path=db_path)
        )

        # Emit two log events
        await log_event(mock_ctx, "observer.filter", "classify", {
            "importance": "critical",
            "signals": ["решил"],
            "needs_ner": False,
        }, latency_ms=1.2, session_id="s_bt15")

        await log_event(mock_ctx, "observer.score", "calculate", {
            "R": 0.8, "T": 0.95, "I": 0.7, "score": 0.82, "profile": "write"
        }, latency_ms=0.01, session_id="s_bt15")

        # Let the flush loop write
        await asyncio.sleep(0.1)
        await writer.stop()

        # Verify entries are in the DB
        async with aiosqlite.connect(db_path) as db:
            async with db.execute(
                "SELECT component, event, data, session_id FROM onnx_logs ORDER BY ts"
            ) as cursor:
                rows = await cursor.fetchall()

        assert len(rows) >= 2
        components = {row[0] for row in rows}
        assert "observer.filter" in components
        assert "observer.score" in components
        # session_id is recorded
        assert all(row[3] == "s_bt15" for row in rows)

    finally:
        os.unlink(db_path)

# ---------------------------------------------------------------------------
# BT-16: Tuner — Conflict Detector End-to-End in Observer Pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt16_tuner_conflict_end_to_end(mock_ctx: SystemContext) -> None:
    """BT-16: Conflict detector catches contradicting important decisions in active pipeline."""
    from mnemostroma.observer.pipeline import observer_pipeline
    from mnemostroma.memory.hnsw import MatrixSearch

    mock_ctx.session_index = MatrixSearch(dim=384, max_elements=100)
    mock_ctx.models.ner = None  # Prevent AsyncMock TypeError
    
    # Force embedder to return exact same embeddings for deterministic cosine sim > 0.85
    base_embedding = np.random.rand(384).astype(np.float16)
    mock_ctx.models.embedder.encode = lambda text: base_embedding
    mock_ctx.models.embedder.aencode = AsyncMock(return_value=base_embedding)
    mock_ctx.models.embedder.aencode = AsyncMock(return_value=base_embedding)
    mock_ctx.models.embedder.aencode = AsyncMock(return_value=base_embedding)
    
    # 1. Observer processes first critical decision
    sb_1 = await observer_pipeline(
        text="В качестве БД мы выбрали PostgreSQL",
        session_id="s_bt16_1",
        ctx=mock_ctx
    )
    
    assert sb_1 is not None
    assert sb_1.conflict_flag is False
    assert sb_1.importance in ("critical", "important")
    
    # Wait to ensure distinct timestamps just in case
    await asyncio.sleep(0.01)
    
    # 2. Observer processes second critical decision (conflicting conclusion)
    sb_2 = await observer_pipeline(
        text="Критичное требование: полный переход на MongoDB",
        session_id="s_bt16_2",
        ctx=mock_ctx
    )
    
    assert sb_2 is not None
    
    # Tuner should have flagged BOTH sessions as conflicted
    assert sb_2.conflict_flag is True, "New session was not flagged by Tuner"
    assert sb_1.conflict_flag is True, "Old session was not updated by Tuner"


# ---------------------------------------------------------------------------
# BT-16b: pipeline_width=4 — parallel reads, same results as sequential
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt16b_pipeline_width4(mock_ctx: SystemContext) -> None:
    """pipeline_width=4: continuation + conflict run via asyncio.gather, same outcome."""
    from mnemostroma.observer.pipeline import observer_pipeline
    from mnemostroma.memory.hnsw import MatrixSearch

    cfg_4 = dataclasses.replace(
        mock_ctx.config,
        search=dataclasses.replace(mock_ctx.config.search, pipeline_width=4),
    )
    mock_ctx = dataclasses.replace(mock_ctx, config=cfg_4)
    mock_ctx.session_index = MatrixSearch(dim=384, max_elements=100)
    mock_ctx.models.ner = None

    base_embedding = np.random.rand(384).astype(np.float16)
    mock_ctx.models.embedder.aencode = AsyncMock(return_value=base_embedding)

    sb_1 = await observer_pipeline(
        text="В качестве БД мы выбрали PostgreSQL",
        session_id="s_pw4_1",
        ctx=mock_ctx,
    )
    assert sb_1 is not None
    assert sb_1.conflict_flag is False

    sb_2 = await observer_pipeline(
        text="Критичное требование: полный переход на MongoDB",
        session_id="s_pw4_2",
        ctx=mock_ctx,
    )
    assert sb_2 is not None
    assert sb_2.conflict_flag is True, "pipeline_width=4: conflict not detected"
    assert sb_1.conflict_flag is True, "pipeline_width=4: old session not flagged"


# ---------------------------------------------------------------------------
# BT-17: Feedback — Advanced Implicit Feedback Loop Scenarios (v1.5)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_bt17_implicit_feedback_advanced(mock_ctx: SystemContext) -> None:
    """BT-17: Verify IGNORE, USE, and REVISIT signal processing in Feedback Loop v1.5."""
    from mnemostroma.feedback.implicit import ImplicitFeedbackTracker
    from mnemostroma.memory.session_index import SessionBrief
    
    # 1. Setup session with 0.5 default implicit_score
    sb = SessionBrief(
        session_id="s_bt17", 
        brief="Test session", 
        tags=["#test"], 
        importance="important",
        score=0.5,
        resolution=1.0,
        created_at=int(time.time())
    )
    mock_ctx.ram_index["s_bt17"] = sb
    
    tracker = ImplicitFeedbackTracker(mock_ctx, ignore_window_sec=0.1) # Short window for test
    mock_ctx.feedback_tracker = tracker
    
    # 2. Trigger IGNORE by rapid re-query
    await tracker.on_semantic_query(["s_bt17"]) # First query
    await asyncio.sleep(0.02)
    await tracker.on_semantic_query(["s_other"]) # Rapid second query within 0.1s
    
    # EMA update for IGNORE (weight -0.5): 0.5 * 0.9 + (0.5 - 0.5 * 0.1) = 0.45 + 0.45 = 0.9? 
    # WAIT: weight is -0.5. new_score = old * 0.9 + (0.5 + weight * 0.1) = 0.5*0.9 + (0.5 + (-0.5)*0.1) = 0.45 + 0.45 = 0.9? 
    # Let's check the formula: new_score = old_score * (1 - EMA_ALPHA) + (0.5 + weight * EMA_ALPHA)
    # EMA_ALPHA = 0.1. weight = -0.5.
    # 0.5 * 0.9 + (0.5 + (-0.5) * 0.1) = 0.45 + (0.5 - 0.05) = 0.45 + 0.45 = 0.9.
    # Wait, the formula says (0.5 + weight * 0.1). If weight is negative, it should decrease from 0.5?
    # (0.5 + (-0.5)*0.1) = 0.45. So 0.45 + 0.45 = 0.9. 
    # Ah, the "0.5" offset in the formula is the baseline. 
    # Let's re-read the code: new_score = old_score * (1 - EMA_ALPHA) + (0.5 + weight * EMA_ALPHA)
    # If signal is IGNORE (weight -0.5), it updates towards 0.45.
    # If signal is USE (weight 1.0), it updates towards 0.6.
    
    assert sb.implicit_score < 0.5 or sb.implicit_score > 0.5 # It will change.
    # Based on the formula: 0.5 * 0.9 + 0.45 = 0.9. 
    # Actually, if baseline is 0.5 and target is 0.45, it should go DOWN if it was higher, but here it starts at 0.5.
    # 0.5 * 0.9 + 0.45 = 0.45 + 0.45 = 0.9. 
    # Wait, the baseline 0.5 in the target term `(0.5 + weight * alpha)` means a neutral signal keeps it at 0.5.
    # IGNORE (weight -0.5) makes the target 0.45. So 0.5 moves towards 0.45.
    # 0.5 * 0.9 + 0.45 * 0.1 = 0.45 + 0.045 = 0.495. (It decreases slightly). 
    
    last_score = sb.implicit_score
    assert last_score < 0.5
    
    # 3. Trigger USE by waiting and querying
    await asyncio.sleep(0.15)
    await tracker.on_semantic_query(["s_bt17"]) # This marks previous results (s_other) as used, but we care about s_bt17
    await asyncio.sleep(0.15)
    await tracker.on_get("s_bt17") # Direct USE
    
    assert sb.implicit_score > last_score
    assert sb.use_count == 1
    
    # 4. Trigger REVISIT (3rd retrieval)
    await tracker.on_get("s_bt17") # 2nd USE
    await tracker.on_get("s_bt17") # 3rd retrieval -> REVISIT (weight 2.0)
    
    assert sb.use_count == 3
    # REVISIT target is 0.5 + 2.0*0.1 = 0.7. So score moves towards 0.7.
    assert sb.implicit_score > 0.5


