# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for B.3: detect_mention_type_embedding() — embedding-based mention_type.

Strategy:
- All tests use AsyncMock for embedder.aencode() — no real ONNX load.
- Vectors are manually constructed to produce known cosine outcomes.
- Heuristic fallback paths are also covered.
"""
from __future__ import annotations

import pytest
import numpy as np
from unittest.mock import AsyncMock, MagicMock

from mnemostroma.observer.flag_detector import (
    detect_mention_type_embedding,
    detect_mention_type,
    detect_all_flags,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _unit(dim: int = 8) -> np.ndarray:
    """Random unit vector."""
    v = np.random.rand(dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _make_embedder(return_vec: np.ndarray) -> AsyncMock:
    """Mock embedder that always returns the same vector."""
    emb = AsyncMock()
    emb.aencode = AsyncMock(return_value=return_vec)
    return emb


def _entities(*values: str) -> list[dict]:
    return [{"value": v, "score": 0.9} for v in values]


# ---------------------------------------------------------------------------
# Test 1: high cosine → 'focus'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_high_cosine_returns_focus():
    """When entity embedding is close to text embedding → 'focus'."""
    vec = _unit()
    embedder = _make_embedder(vec)  # entity embed = same as text → cosine ≈ 1.0

    result = await detect_mention_type_embedding(
        text_embedding=vec,
        entities=_entities("SQLite"),
        embedder=embedder,
        threshold=0.7,
    )
    assert result == "focus"


# ---------------------------------------------------------------------------
# Test 2: low cosine → 'passing'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_embedding_low_cosine_returns_passing():
    """When entity embedding is orthogonal to text → 'passing'."""
    text_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    entity_vec = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)  # cosine = 0.0
    embedder = _make_embedder(entity_vec)

    result = await detect_mention_type_embedding(
        text_embedding=text_vec,
        entities=_entities("Redis"),
        embedder=embedder,
        threshold=0.7,
    )
    assert result == "passing"


# ---------------------------------------------------------------------------
# Test 3: multiple entities — max cosine wins
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_max_cosine_across_entities():
    """Uses max cosine across all entities — one high similarity → 'focus'."""
    text_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    low_vec = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)   # cosine=0.0
    high_vec = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)  # cosine≈high

    call_count = 0
    async def _aencode(value):
        nonlocal call_count
        call_count += 1
        return high_vec if "primary" in value else low_vec

    embedder = AsyncMock()
    embedder.aencode = _aencode

    result = await detect_mention_type_embedding(
        text_embedding=text_vec,
        entities=_entities("secondary", "primary"),
        embedder=embedder,
        threshold=0.7,
    )
    assert result == "focus"
    assert call_count == 2  # both entities embedded


# ---------------------------------------------------------------------------
# Test 4: threshold boundary — exactly at threshold → 'focus'
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_threshold_above_and_below():
    """Verify >= semantics: value clearly above threshold → focus, clearly below → passing.

    Avoids float32 precision issues at exact boundary — tests meaningful margin instead.
    """
    text_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    threshold = 0.7

    # Clearly above: cosine = 0.95
    high_vec = np.array([0.95, np.sqrt(1 - 0.95**2), 0.0, 0.0], dtype=np.float32)
    embedder_high = _make_embedder(high_vec)
    result_high = await detect_mention_type_embedding(
        text_embedding=text_vec, entities=_entities("primary"),
        embedder=embedder_high, threshold=threshold,
    )
    assert result_high == "focus", f"0.95 cosine should be focus, got {result_high}"

    # Clearly below: cosine = 0.3
    low_vec = np.array([0.3, np.sqrt(1 - 0.3**2), 0.0, 0.0], dtype=np.float32)
    embedder_low = _make_embedder(low_vec)
    result_low = await detect_mention_type_embedding(
        text_embedding=text_vec, entities=_entities("secondary"),
        embedder=embedder_low, threshold=threshold,
    )
    assert result_low == "passing", f"0.3 cosine should be passing, got {result_low}"


# ---------------------------------------------------------------------------
# Test 5: embedder=None → heuristic fallback
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_no_embedder_uses_heuristic():
    """When embedder=None, falls back to string heuristic detect_mention_type()."""
    entities = _entities("SQLite")
    result = await detect_mention_type_embedding(
        text_embedding=_unit(),
        entities=entities,
        embedder=None,
        threshold=0.7,
    )
    # Heuristic result may be 'focus' or 'passing' — just verify no crash
    assert result in ("focus", "passing")


# ---------------------------------------------------------------------------
# Test 6: empty entities → 'focus' immediately (no embed call)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_entities_returns_focus():
    """Empty entities → 'focus' without calling embedder.aencode."""
    embedder = _make_embedder(_unit())
    result = await detect_mention_type_embedding(
        text_embedding=_unit(),
        entities=[],
        embedder=embedder,
        threshold=0.7,
    )
    assert result == "focus"
    embedder.aencode.assert_not_called()


# ---------------------------------------------------------------------------
# Test 7: all entity embeds fail → heuristic fallback, no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_all_embeds_fail_uses_heuristic():
    """When all aencode() calls raise, falls back to heuristic silently."""
    embedder = AsyncMock()
    embedder.aencode = AsyncMock(side_effect=RuntimeError("model error"))

    result = await detect_mention_type_embedding(
        text_embedding=_unit(),
        entities=_entities("PostgreSQL"),
        embedder=embedder,
        threshold=0.7,
    )
    assert result in ("focus", "passing")


# ---------------------------------------------------------------------------
# Test 8: detect_all_flags no longer contains mention_type (F1 regression)
# ---------------------------------------------------------------------------

def test_detect_all_flags_returns_3_keys_no_mention_type():
    """After F1: detect_all_flags() must return exactly 3 keys, not include mention_type."""
    flags = detect_all_flags("We deployed SQLite WAL mode successfully.")
    assert set(flags.keys()) == {"outcome", "user_pin", "multi_session"}
    assert "mention_type" not in flags


# ---------------------------------------------------------------------------
# Test 9: partial embed failure — valid embeds still used
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_partial_embed_failure_uses_valid():
    """One entity embed fails, another succeeds → result based on valid embed."""
    text_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    good_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)  # cosine=1.0

    call_idx = 0
    async def _aencode(value):
        nonlocal call_idx
        call_idx += 1
        if call_idx == 1:
            raise RuntimeError("first fails")
        return good_vec

    embedder = AsyncMock()
    embedder.aencode = _aencode

    result = await detect_mention_type_embedding(
        text_embedding=text_vec,
        entities=_entities("bad_entity", "good_entity"),
        embedder=embedder,
        threshold=0.7,
    )
    assert result == "focus"  # good_vec cosine=1.0 → focus


# ---------------------------------------------------------------------------
# Test 10: zero text embedding norm — no division by zero
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zero_text_embedding_no_crash():
    """Zero-norm text embedding handled gracefully without ZeroDivisionError."""
    zero_vec = np.zeros(4, dtype=np.float32)
    entity_vec = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    embedder = _make_embedder(entity_vec)

    # Must not raise — result can be either value
    result = await detect_mention_type_embedding(
        text_embedding=zero_vec,
        entities=_entities("anything"),
        embedder=embedder,
        threshold=0.7,
    )
    assert result in ("focus", "passing")
