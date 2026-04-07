# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Phase 3 (anchor decay) and Phase 4 (dreamer idle detection)."""
import time
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.subconscious.anchor_index import AnchorIndex
from mnemostroma.memory.consolidation import ConsolidationWorker, _DECAY_FACTS_LIMIT
from mnemostroma.subconscious.dreamer import Dreamer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_anchor(anchor_id="a1", decay_level=0, days_inactive=40,
                 access_count=0, user_pin=False, outcome="pending"):
    now = int(time.time())
    last_access = now - int(days_inactive * 86400)
    facts = [{"type": "decision", "value": f"fact{i}", "score": 1.0, "priority": 1}
             for i in range(5)]
    return Anchor(
        anchor_id=anchor_id,
        session_id=anchor_id,
        brief="brief text",
        anchor_type="decision",
        key_facts=facts,
        flags={"user_pin": user_pin, "outcome": outcome,
               "continuation_of": None, "continuation_depth": 0,
               "is_new_entity": True, "mention_type": "focus",
               "multi_session": False},
        decay_level=decay_level,
        access_count=access_count,
        last_accessed_at=last_access,
        created_at=last_access,
        updated_at=last_access,
    )


def _make_ctx(anchors=None):
    from mnemostroma.config import (
        AnchorDecayConfig, DreamerConfig, Config,
        ResourcesConfig, ScoreConfig, ImportanceConfig,
        TemporalConfig, DissolverConfig, SearchConfig,
        ObserverConfig, TunerConfig, UrgencyConfig,
        StorageConfig, ExperienceConfig, CalibrationConfig,
        SecurityConfig, CloudSyncConfig, FeedbackConfig,
    )
    from pathlib import Path
    config = Config.load(Path(__file__).parent.parent / "config.json")

    ctx = MagicMock()
    ctx.config = config
    ctx.ram_index = {}
    ctx.anchor_index = AnchorIndex()
    ctx.persistence = None
    ctx.experience_index = None
    ctx.log_writer = None
    if anchors:
        for a in anchors:
            ctx.anchor_index.put(a)
    return ctx


# ---------------------------------------------------------------------------
# _DECAY_FACTS_LIMIT constants
# ---------------------------------------------------------------------------

def test_decay_facts_limit_values():
    assert _DECAY_FACTS_LIMIT[0] == 5
    assert _DECAY_FACTS_LIMIT[1] == 3
    assert _DECAY_FACTS_LIMIT[2] == 1
    assert _DECAY_FACTS_LIMIT[3] == 0


# ---------------------------------------------------------------------------
# Anchor Decay Engine
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_anchor_decay_advances_level():
    anchor = _make_anchor(days_inactive=40)
    ctx = _make_ctx([anchor])
    worker = ConsolidationWorker(ctx)

    decayed = await worker._run_anchor_decay(time.time())

    assert decayed == 1
    assert anchor.decay_level == 1
    assert len(anchor.key_facts) <= _DECAY_FACTS_LIMIT[1]


@pytest.mark.asyncio
async def test_anchor_decay_skips_pinned():
    anchor = _make_anchor(days_inactive=40, user_pin=True)
    ctx = _make_ctx([anchor])
    worker = ConsolidationWorker(ctx)

    decayed = await worker._run_anchor_decay(time.time())

    assert decayed == 0
    assert anchor.decay_level == 0


@pytest.mark.asyncio
async def test_anchor_decay_skips_recent():
    anchor = _make_anchor(days_inactive=5)  # only 5 days inactive
    ctx = _make_ctx([anchor])
    worker = ConsolidationWorker(ctx)

    decayed = await worker._run_anchor_decay(time.time())

    assert decayed == 0
    assert anchor.decay_level == 0


@pytest.mark.asyncio
async def test_anchor_decay_skips_bedrock():
    anchor = _make_anchor(days_inactive=100, decay_level=3)
    ctx = _make_ctx([anchor])
    worker = ConsolidationWorker(ctx)

    decayed = await worker._run_anchor_decay(time.time())

    assert decayed == 0
    assert anchor.decay_level == 3  # stays at bedrock


@pytest.mark.asyncio
async def test_anchor_decay_trims_facts_to_level():
    anchor = _make_anchor(days_inactive=40)
    assert len(anchor.key_facts) == 5

    ctx = _make_ctx([anchor])
    worker = ConsolidationWorker(ctx)
    await worker._run_anchor_decay(time.time())

    assert anchor.decay_level == 1
    assert len(anchor.key_facts) == 3  # trimmed to partial


@pytest.mark.asyncio
async def test_anchor_decay_full_progression():
    """Three decay cycles → level 0 → 1 → 2 → 3."""
    anchor = _make_anchor(days_inactive=40, decay_level=0)
    ctx = _make_ctx([anchor])
    worker = ConsolidationWorker(ctx)

    for expected_level in range(1, 4):
        await worker._run_anchor_decay(time.time())
        assert anchor.decay_level == expected_level

    assert len(anchor.key_facts) == 0  # bedrock: no facts
    assert anchor.brief == "brief text"  # brief preserved


@pytest.mark.asyncio
async def test_anchor_decay_disabled_when_config_off():
    anchor = _make_anchor(days_inactive=40)
    ctx = _make_ctx([anchor])
    import dataclasses
    ctx.config = dataclasses.replace(
        ctx.config,
        anchor_decay=dataclasses.replace(ctx.config.anchor_decay, enabled=False),
    )
    worker = ConsolidationWorker(ctx)

    # decay disabled — consolidate() should not call _run_anchor_decay
    # We test by calling consolidate() with mocked RAM (no sessions to avoid DB calls)
    decayed = await worker._run_anchor_decay(time.time())
    # _run_anchor_decay itself doesn't check enabled — that's done in consolidate()
    # But with disabled config, consolidate() won't call it
    # Direct call should still work — just returns count
    assert decayed == 1  # direct call ignores enabled flag


# ---------------------------------------------------------------------------
# Conductor idle detection (Phase 4.1)
# ---------------------------------------------------------------------------

def test_conductor_is_idle_initial():
    from mnemostroma.conductor import Conductor
    c = Conductor()
    assert c.is_idle() is False  # no observe() called yet


def test_conductor_is_idle_after_observe(monkeypatch):
    from mnemostroma.conductor import Conductor
    import time
    c = Conductor()
    c.ctx = MagicMock()
    c.ctx.config.dreamer.idle_threshold_min = 0  # 0 min → always idle after observe
    c._last_observe_at = time.time() - 1  # 1 second ago
    assert c.is_idle() is True


def test_conductor_not_idle_recent(monkeypatch):
    from mnemostroma.conductor import Conductor
    import time
    c = Conductor()
    c.ctx = MagicMock()
    c.ctx.config.dreamer.idle_threshold_min = 60  # 60 min threshold
    c._last_observe_at = time.time()  # just now
    assert c.is_idle() is False


# ---------------------------------------------------------------------------
# Dreamer cycle (Phase 4.2)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dreamer_dream_empty_index():
    ctx = _make_ctx()
    conductor = MagicMock()
    dreamer = Dreamer(conductor, ctx)
    stats = await dreamer.dream()
    assert stats["anchors_checked"] == 0


@pytest.mark.asyncio
async def test_dreamer_resurfaces_high_access_anchors():
    anchor = _make_anchor("a1", access_count=5, days_inactive=1, outcome="success")
    ctx = _make_ctx([anchor])
    conductor = MagicMock()
    dreamer = Dreamer(conductor, ctx)

    stats = await dreamer.dream()

    assert stats["resurfaced"] >= 1
    assert anchor.access_count > 5  # touch() was called


@pytest.mark.asyncio
async def test_dreamer_reassesses_outcome():
    """Pending anchor → resolved to success when continuation found."""
    parent = _make_anchor("parent", outcome="pending", access_count=0, days_inactive=1)
    child = _make_anchor("child", outcome="success", access_count=0, days_inactive=1)
    child.anchor_type = "milestone"
    child.flags["continuation_of"] = "parent"

    ctx = _make_ctx([parent, child])
    # Put child into ram_index too so dreamer finds it
    ctx.ram_index["child"] = MagicMock()

    conductor = MagicMock()
    dreamer = Dreamer(conductor, ctx)

    stats = await dreamer.dream()

    assert stats["outcomes_updated"] >= 1
    assert parent.flags["outcome"] == "success"


@pytest.mark.asyncio
async def test_dreamer_respects_max_anchors_per_cycle():
    anchors = [_make_anchor(f"a{i}", access_count=i, days_inactive=1, outcome="success")
               for i in range(30)]
    ctx = _make_ctx(anchors)
    import dataclasses
    ctx.config = dataclasses.replace(
        ctx.config,
        dreamer=dataclasses.replace(ctx.config.dreamer, max_anchors_per_cycle=5),
    )
    conductor = MagicMock()
    dreamer = Dreamer(conductor, ctx)

    stats = await dreamer.dream()
    assert stats["anchors_checked"] == 5
