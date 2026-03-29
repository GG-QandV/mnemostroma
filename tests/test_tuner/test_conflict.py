# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
import numpy as np
import time
from typing import Dict, Any

from mnemostroma.memory.session_index import SessionBrief
from mnemostroma.tuner.conflict import check_conflict, decisions_contradict

# A mock Context to satisfy SystemContext typing for check_conflict
class MockEmbedder:
    def encode(self, text: str) -> np.ndarray:
        # returns deterministic vectors based on string hash for simple testing
        np.random.seed(hash(text) & 0xFFFFFFFF)
        return np.random.rand(768).astype(np.float16)

class MockHNSW:
    def __init__(self):
        self.vectors = []
        self.labels = []
        
    def add_items(self, items, labels):
        self.vectors.extend(items)
        self.labels.extend(labels)
        
    def get_current_count(self):
        return len(self.vectors)
        
    def knn_query(self, query, k=10):
        if not self.vectors:
            return [[]], [[]]
            
        distances = []
        for v in self.vectors:
            dist = 1.0 - float(np.dot(query[0], v) / (np.linalg.norm(query[0]) * np.linalg.norm(v)))
            distances.append(dist)
            
        # Simulating returning all sorted
        sorted_indices = np.argsort(distances)[:k]
        sorted_labels = [self.labels[i] for i in sorted_indices]
        sorted_dists = [distances[i] for i in sorted_indices]
        
        return [sorted_labels], [sorted_dists]

class MockContext:
    def __init__(self):
        self.ram_index = {}
        self.hnsw_session = MockHNSW()
        self.id_to_sid = {}
        self.sid_to_id = {}
        self.models = type('obj', (object,), {'embedder': MockEmbedder()})

@pytest.fixture
def mock_ctx():
    return MockContext()

@pytest.fixture
def base_embedding():
    np.random.seed(42)
    return np.random.rand(512).astype(np.float16)

def test_decisions_contradict():
    embedder = MockEmbedder()
    
    # Matching topics, different conclusions
    sb1 = SessionBrief(
        session_id="s1", brief="Решили использовать PostgreSQL вместо MongoDB", 
        tags=["database"], importance="critical", score=0.9, resolution=1.0, created_at=0,
        embedding=np.ones(768).astype(np.float16)
    )
    
    # Vector simulation for "highly similar topic"
    sim_vec = np.ones(768).astype(np.float16)
    sim_vec[0] = 0.999 # slight perturbation
    
    sb2 = SessionBrief(
        session_id="s2", brief="Выбрали MongoDB вместо PostgreSQL категорически", 
        tags=["database"], importance="critical", score=0.9, resolution=1.0, created_at=0,
        embedding=sim_vec
    )
    
    # Should flag as contradiction
    contradict = decisions_contradict(sb1, sb2, embedder)
    assert contradict == True
    
    # Non-conflicting (different topics altogether)
    sb3 = SessionBrief(
        session_id="s3", brief="Используем JWT для авторизации", 
        tags=["auth"], importance="critical", score=0.9, resolution=1.0, created_at=0,
        embedding=np.zeros(768).astype(np.float16)
    )
    
    contradict2 = decisions_contradict(sb1, sb3, embedder)
    assert contradict2 == False  # low cosine sim
    

def test_check_conflict(mock_ctx, base_embedding):
    """Test full conflict checker scanning HNSW and RAM index."""
    # Insert existing session
    sb_old = SessionBrief(
        session_id="old_1", brief="GraphQL API selected as primary protocol", 
        tags=["api", "graphql"], importance="critical", score=0.9, resolution=1.0, created_at=int(time.time()),
        embedding=base_embedding
    )
    
    mock_ctx.ram_index["old_1"] = sb_old
    mock_ctx.sid_to_id["old_1"] = 1
    mock_ctx.id_to_sid[1] = "old_1"
    mock_ctx.hnsw_session.add_items([base_embedding], [1])
    
    # New session matching the topic but contradicting the decision
    sim_vec = base_embedding.copy()
    sim_vec[10] += 0.001  # extremely similar, almost identical topic
    
    sb_new = SessionBrief(
        session_id="new_1", brief="REST API selected instead of GraphQL", 
        tags=["api", "rest"], importance="critical", score=0.9, resolution=1.0, created_at=int(time.time()),
        embedding=sim_vec
    )
    
    is_conflict = check_conflict(sb_new, mock_ctx)
    
    assert is_conflict is True
    assert sb_new.conflict_flag is True
    assert sb_old.conflict_flag is True

def test_conflict_ignores_background(mock_ctx, base_embedding):
    """Test that background/important sessions do not trigger critical conflicts if not critical."""
    sb_old = SessionBrief(
        session_id="old_2", brief="I like GraphQL", 
        tags=["api", "graphql"], importance="background", score=0.5, resolution=1.0, created_at=int(time.time()),
        embedding=base_embedding
    )
    
    mock_ctx.ram_index["old_2"] = sb_old
    mock_ctx.sid_to_id["old_2"] = 2
    mock_ctx.id_to_sid[2] = "old_2"
    mock_ctx.hnsw_session.add_items([base_embedding], [2])
    
    sim_vec = base_embedding.copy()
    sb_new = SessionBrief(
        session_id="new_2", brief="GraphQL is replaced by REST", 
        tags=["api", "rest"], importance="critical", score=0.9, resolution=1.0, created_at=int(time.time()),
        embedding=sim_vec
    )
    
    is_conflict = check_conflict(sb_new, mock_ctx)
    
    # Because old is 'background', it shouldn't trigger critical conflict
    assert is_conflict is False
    assert sb_new.conflict_flag is False
