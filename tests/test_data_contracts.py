# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import asyncio
import time
import numpy as np
import json
from unittest.mock import MagicMock, AsyncMock, patch
from pathlib import Path
from dataclasses import replace

from mnemostroma.conductor import Conductor
from mnemostroma.core import SystemContext
from mnemostroma.config import Config
from mnemostroma.storage.persistence import PersistenceLayer
from mnemostroma.storage.sqlite import DatabaseManager, init_db
from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.subconscious.anchor import Anchor
from mnemostroma.integration.proxy import ConductorProxy
from mnemostroma.tools.read import ctx_get, ctx_semantic

@pytest.fixture
async def mock_ctx():
    """Context with in-memory SQLite and mocked models."""
    config_path = Path("src/mnemostroma/config_default.json")
    if not config_path.exists():
        config_path = Path(__file__).parent.parent / "src/mnemostroma/config_default.json"
        
    config = Config.load(config_path)
    ctx = SystemContext(config=config)
    
    # Mock models for search
    mock_embedder = AsyncMock()
    # Return a deterministic vector for search testing (align with 768d spec)
    mock_embedder.aencode.side_effect = lambda text: np.zeros(768).astype(np.float32)
    mock_embedder.dim = 768
    
    ctx.models = MagicMock()
    ctx.models.embedder = mock_embedder
    ctx.models.ner = AsyncMock()
    ctx.models.ner.extract_entities.return_value = []
    ctx.models.reranker = None
    
    # Indices
    ctx.session_index = MagicMock()
    # Mock KNN to return a match if we search
    ctx.session_index.knn_query.return_value = (np.array([0]), np.array([0.0]))
    ctx.session_index.get_current_count.return_value = 1
    
    # Persistence
    db = await init_db(":memory:", config)
    db_manager = DatabaseManager(db, config)
    await db_manager.start()
    ctx.persistence = PersistenceLayer(db_manager)
    ctx.persistence.wire_ctx(ctx)
    ctx.db = db
    
    return ctx

@pytest.mark.asyncio
async def test_session_brief_serialization_roundtrip(mock_ctx):
    """Verify that SessionBrief survives SQLite round-trip with no data loss."""
    # SQLite storage uses float16 for embeddings (2 bytes per element)
    # We must ensure we provide float16 or the round-trip size will mismatch
    emb = np.random.rand(768).astype(np.float16)
    
    sb = SessionBrief(
        session_id="contract_test_01",
        brief="Testing complex data serialization",
        tags=["pytest", "contract", "v1.7.1"],
        importance="critical",
        score=0.987,
        resolution=0.85,
        created_at=int(time.time()),
        conflict_flag=True,
        urgency="deadline_h",
        deadline_ts=int(time.time()) + 3600,
        urgency_expired=False,
        bare_entity=False,
        embedding=emb,
        implicit_score=0.75,
        intensity=0.9
    )
    
    # Enqueue and flush
    mock_ctx.persistence.enqueue_session(sb)
    await mock_ctx.persistence.flush()
    
    # Load back
    loaded = await mock_ctx.persistence.get_session_by_id(sb.session_id)
    assert loaded is not None
    
    # Field-by-field comparison
    assert loaded.session_id == sb.session_id
    assert loaded.brief == sb.brief
    assert loaded.tags == sb.tags
    assert loaded.importance == sb.importance
    assert round(loaded.resolution, 2) == round(sb.resolution, 2)
    assert loaded.intensity == sb.intensity
    assert loaded.conflict_flag == sb.conflict_flag
    assert loaded.urgency == sb.urgency
    assert loaded.deadline_ts == sb.deadline_ts
    assert loaded.bare_entity == sb.bare_entity
    assert round(loaded.implicit_score, 2) == round(sb.implicit_score, 2)
    
    # Embedding check
    assert loaded.embedding.shape == (768,)
    # Compare with small tolerance due to float16
    np.testing.assert_allclose(loaded.embedding.astype(float), sb.embedding.astype(float), atol=1e-3)

@pytest.mark.asyncio
async def test_anchor_serialization_roundtrip(mock_ctx):
    """Verify that Anchors survive SQLite round-trip with complex nested t_rel."""
    anchor = Anchor(
        anchor_id="anc_contract_01",
        session_id="s_anc_01",
        brief="Permanent decision about architecture",
        anchor_type="decision",
        key_facts=[{"fact": "numpy matrix search", "confidence": 1.0}],
        flags={"user_pinned": True, "v1.7_compat": True},
        t_rel={
            "after": ["arch_v1.6"],
            "before": ["arch_v1.8"],
            "caused_by": ["adr_002"],
            "during": []
        },
        decay_level=0,
        access_count=5,
        last_accessed_at=int(time.time()),
        created_at=int(time.time()),
        updated_at=int(time.time())
    )
    
    await mock_ctx.persistence.save_anchor(anchor)
    
    # load_anchors returns a list
    loaded_list = await mock_ctx.persistence.load_anchors(limit=1)
    assert len(loaded_list) == 1
    loaded = loaded_list[0]
    
    assert loaded.anchor_id == anchor.anchor_id
    assert loaded.anchor_type == anchor.anchor_type
    assert loaded.key_facts == anchor.key_facts
    assert loaded.flags == anchor.flags
    assert loaded.t_rel == anchor.t_rel
    assert loaded.access_count == anchor.access_count

@pytest.mark.asyncio
async def test_mcp_routing_contract(mock_ctx):
    """Verify that data present in SystemContext is correctly routed to MCP tools."""
    sb = SessionBrief(
        session_id="mcp_session", brief="MCP Routing Goal", 
        tags=["mcp"], importance="important", score=1.0, 
        resolution=1.0, created_at=int(time.time()),
        embedding=np.zeros(768).astype(np.float16)
    )
    mock_ctx.ram_index[sb.session_id] = sb
    mock_ctx.id_to_sid = {0: sb.session_id}
    mock_ctx.sid_to_id = {sb.session_id: 0}
    
    # 1. Test ctx_get
    fetched = await ctx_get(sb.session_id, mock_ctx)
    assert fetched == sb
    
    # 2. Test ctx_semantic
    # ctx_semantic calls semantic_search which uses HNSW knn_query
    with patch("mnemostroma.tools.read.semantic_search", new=AsyncMock(return_value=[sb])):
        results = await ctx_semantic("routing question", mock_ctx, k=1, top_n=1)
        assert len(results) == 1
        assert results[0].session_id == sb.session_id

@pytest.mark.asyncio
async def test_conductor_proxy_xml_schema(mock_ctx):
    """Verify that ConductorProxy generates exactly the XML tags expected by the frontend."""
    # Populate context with various memory types
    now = int(time.time())
    mock_ctx.ram_index = {
        "s_p": SessionBrief("s_p", "Rule: no torch", ["meta"], "principle", 1.0, 1.0, now),
        "s_d": SessionBrief("s_d", "Decided: use numpy", ["arch"], "important", 0.9, 1.0, now),
        "s_c": SessionBrief("s_c", "Conflict: HNSW vs Matrix", ["tuner"], "background", 0.5, 1.0, now, conflict_flag=True),
        "s_u": SessionBrief("s_u", "Task: Alpha Build", ["ops"], "important", 0.8, 1.0, now, urgency="deadline_h", deadline_ts=now+3600)
    }
    
    # mock_ctx.urgency_index is needed for deadline building
    mock_ctx.urgency_index = {
        "s_u": {"title": "Task: Alpha Build", "deadline_ts": now+3600, "expired": False}
    }
    
    proxy = ConductorProxy(mock_ctx)
    # inject(user_message)
    with patch("mnemostroma.integration.proxy.ctx_semantic", new=AsyncMock(return_value=[mock_ctx.ram_index["s_d"]])):
        result = await proxy.inject("What was the decision?")
    
    xml = result.context
    
    # Essential Schema Validation
    assert "<memory_context" in xml
    assert "<principles>" in xml
    assert "- Rule: no torch" in xml
    assert "<decisions>" in xml
    assert "- Decided: use numpy" in xml
    assert "<conflicts>" in xml
    assert "- Conflict: HNSW vs Matrix" in xml
    assert "<deadlines>" in xml
    assert "Task: Alpha Build" in xml
    assert "<relevant>" in xml
    assert "s_d: Decided: use numpy" in xml
    assert "</memory_context>" in xml
    
    # Stats field check
    assert "tokens" in result.stats
    assert "semantic_ms" in result.stats
