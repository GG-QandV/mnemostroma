# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import asyncio
import time
import numpy as np
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
from dataclasses import replace

from mnemostroma.conductor import Conductor
from mnemostroma.core import SystemContext
from mnemostroma.config import Config
from mnemostroma.storage.persistence import PersistenceLayer
from mnemostroma.storage.sqlite import DatabaseManager, init_db
from mnemostroma.memory.experience import ExperienceCluster
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.memory.dissolver import Dissolver

@pytest.fixture
async def mock_ctx():
    """Context with in-memory SQLite and mocked models."""
    config_path = Path("src/mnemostroma/config_default.json")
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "src/mnemostroma/config_default.json"
        
    config = Config.load(config_path)
    ctx = SystemContext(config=config)
    
    # Mock models
    mock_embedder = AsyncMock()
    mock_embedder.aencode.side_effect = lambda text: np.random.rand(384).astype(np.float32)
    mock_embedder.dim = 384
    
    mock_ner = AsyncMock()
    mock_ner.extract_entities.return_value = []
    
    ctx.models = MagicMock()
    ctx.models.embedder = mock_embedder
    ctx.models.ner = mock_ner
    ctx.models.reranker = None
    
    # Indices
    ctx.session_index = MagicMock()
    ctx.session_index.get_current_count.return_value = 10
    ctx.content_index = MagicMock()
    ctx.experience_index = MagicMock()
    ctx.id_to_sid = {}
    ctx.sid_to_id = {}
    
    # Wire persistence
    db = await init_db(":memory:", config)
    db_manager = DatabaseManager(db, config)
    await db_manager.start()
    ctx.persistence = PersistenceLayer(db_manager)
    ctx.persistence.wire_ctx(ctx)
    ctx.db = db
    
    # Dissolver
    ctx.dissolver = Dissolver(ctx)
    
    return ctx

@pytest.fixture
async def conductor(mock_ctx):
    c = Conductor()
    c.ctx = mock_ctx
    c.proxy = MagicMock()
    return c

@pytest.mark.asyncio
async def test_ram_hot_invariant(conductor):
    """1. RAM_HOT: Session appears in ctx.ram_index after observe()."""
    text = "Important project requirement: use Postgres."
    
    # Mock pipeline dependencies
    with patch("mnemostroma.observer.steps.filter_step.structural_prefilter", return_value=True), \
         patch("mnemostroma.observer.pipeline._marker", new=AsyncMock()) as mock_marker, \
         patch("mnemostroma.observer.pipeline.detect_urgency", return_value=("none", None)), \
         patch("mnemostroma.observer.steps.persist_step.compress_text", return_value=("Postgres", ["tech"])), \
         patch("mnemostroma.memory.scoring.calculate_score", new=AsyncMock(return_value=0.8)), \
         patch("mnemostroma.observer.steps.persist_step.tuner_check", side_effect=lambda sb, ctx: sb), \
         patch("mnemostroma.observer.steps.persist_step.detect_continuation", return_value={"state": "new"}):
        
        # Setup marker result
        mock_marker.return_value = MagicMock()
        from mnemostroma.observer.entities import MarkerAction
        mock_marker.return_value.action = MarkerAction.CREATE_ENTITY
        mock_marker.return_value.entity.importance = 0.6
        mock_marker.return_value.confidence = 0.9
        mock_marker.return_value.emotion = None

        task = await conductor.observe("s_test_01", text)
        await task
    
    assert "s_test_01" in conductor.ctx.ram_index
    assert "Postgres" in conductor.ctx.ram_index["s_test_01"].brief
    assert conductor.ctx.ram_index["s_test_01"].importance == "important"

@pytest.mark.asyncio
async def test_ram_to_disk_invariant(conductor):
    """2. RAM→Disk: Sessions moved to SQLite after flush()."""
    sb = SessionBrief(
        session_id="s_disk_01", brief="test", tags=[], importance="important",
        score=0.5, resolution=1.0, created_at=int(time.time()),
        embedding=np.random.rand(384).astype(np.float32)
    )
    conductor.ctx.ram_index[sb.session_id] = sb
    conductor.ctx.persistence.enqueue_session(sb)
    
    assert conductor.ctx.persistence.pending_writes() == 1
    
    await conductor.ctx.persistence.flush()
    
    briefs = await conductor.ctx.persistence.get_all_session_briefs()
    assert len(briefs) == 1
    assert briefs[0].session_id == "s_disk_01"

@pytest.mark.asyncio
async def test_score_decay(conductor):
    """3. Score decay: Older sessions lose score over time."""
    now = int(time.time())
    emb = np.random.rand(384).astype(np.float32)
    
    s_fresh = SessionBrief(
        session_id="fresh_01", brief="Fresh", tags=[], importance="important",
        score=0.0, resolution=1.0, created_at=now, embedding=emb
    )
    s_old = SessionBrief(
        session_id="old_01", brief="Old", tags=[], importance="important",
        score=0.0, resolution=1.0, created_at=now - (60 * 86400), embedding=emb
    )
    
    conductor.ctx.ram_index["fresh_01"] = s_fresh
    conductor.ctx.ram_index["old_01"] = s_old
    conductor.ctx.id_to_sid = {0: "fresh_01", 1: "old_01"}
    
    # Mocking MatrixSearch results for search.py:semantic_search
    conductor.ctx.session_index.knn_query.return_value = (
        np.array([0, 1], dtype=np.int64), # labels
        np.array([0.0, 0.0], dtype=np.float32) # distances
    )
    
    from mnemostroma.memory.search import semantic_search
    results = await semantic_search("dummy query", conductor.ctx, k=2, top_n=2)
    
    found_fresh = next(r for r in results if r.session_id == "fresh_01")
    found_old = next(r for r in results if r.session_id == "old_01")
    
    assert found_fresh.score > found_old.score

@pytest.mark.asyncio
async def test_dissolver_eviction(conductor):
    """4. Dissolver: Evict sessions when window overflows."""
    new_res = replace(conductor.ctx.config.resources, session_window_size=5)
    conductor.ctx.config = replace(conductor.ctx.config, resources=new_res)
    
    for i in range(10):
        s = SessionBrief(
            session_id=f"s{i}", brief=f"B{i}", tags=[], importance="important",
            score=0.0, resolution=1.0, created_at=int(time.time()),
            implicit_score=0.9, embedding=np.zeros(384)
        )
        conductor.ctx.ram_index[s.session_id] = s
    
    await conductor.ctx.dissolver.check_and_evict()
    assert len(conductor.ctx.ram_index) <= 5

@pytest.mark.asyncio
async def test_anchor_persistence(conductor):
    """5. Anchor persistence: Save and load round-trip."""
    anchor = Anchor(
        anchor_id="test-anc-1",
        session_id="s1",
        brief="Test decision",
        anchor_type="decision",
        key_facts=[{"type": "tech", "value": "python"}],
        flags={"pinned": True},
        created_at=int(time.time()),
        updated_at=int(time.time())
    )
    
    await conductor.ctx.persistence.save_anchor(anchor)
    
    anchors = await conductor.ctx.persistence.load_anchors(limit=10)
    assert len(anchors) == 1
    saved = anchors[0]
    
    assert saved.anchor_id == anchor.anchor_id
    assert saved.anchor_type == anchor.anchor_type

@pytest.mark.asyncio
async def test_experience_layer_round_trip(conductor):
    """7. Experience layer: emotion_* fields preserved."""
    await conductor.ctx.persistence.save_experience(
        tag="test-tag",
        session_count=10,
        score_sum=15.5,
        conflict_count=2,
        last_updated=int(time.time()),
        emotion_positive=5,
        emotion_negative=1,
        emotion_intensity_sum=3.5
    )
    
    loaded_rows = await conductor.ctx.persistence.load_experience()
    assert len(loaded_rows) == 1
    row = loaded_rows[0]
    
    assert row["tag"] == "test-tag"
    assert row["emotion_positive"] == 5
    assert row["emotion_negative"] == 1
    assert row["emotion_intensity_sum"] == 3.5
