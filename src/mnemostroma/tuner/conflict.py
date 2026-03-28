# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np
import logging
import time
import difflib
from typing import Dict, List, Set, Any
from ..core import SystemContext
from ..memory.session_index import SessionBrief

logger = logging.getLogger("mnemostroma.tuner")

def extract_key_entities(text: str) -> Set[str]:
    """Simplified NER: extracts potential nouns and named entities.
    
    Since Anchors are not implemented in Phase 1, we use the `brief` and `tags`
    as the primary source of truth for semantic contradiction detection.
    """
    return set(token.lower() for token in text.split() if len(token) > 4)

def cosine_similarity(vec_a: np.ndarray, vec_b: np.ndarray) -> float:
    """Calculate cosine similarity safely."""
    norm_a = np.linalg.norm(vec_a)
    norm_b = np.linalg.norm(vec_b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(vec_a, vec_b) / (norm_a * norm_b))

def decisions_contradict(
    sb_a: SessionBrief,
    sb_b: SessionBrief,
    embedder: Any,
    sim_threshold: float = 0.85,
    edit_threshold: float = 0.4,
) -> bool:
    """Determine if two session briefs semantically contradict each other.
    
    Assumes `anchors` aren't yet available, relying on `brief` instead of explicit
    Decision objects as designed in `tuner_specification_v1.4.md`.
    
    Returns:
        True: Same subject, but different conclusion (Conflict).
        False: Different subjects or duplicate conclusions.
    """
    text_A = sb_a.brief
    text_B = sb_b.brief
    
    # 2. Embedding via shared embedder (if missing, use stored embedding)
    vec_A = sb_a.embedding
    vec_B = sb_b.embedding
    
    if vec_A is None or vec_B is None:
        return False
        
    # 3. Semantic similarity - same subject?
    sim = cosine_similarity(vec_A, vec_B)
    if sim <= sim_threshold:
        return False # Different topics -> no conflict
        
    # 4. Textual conclusion divergence
    edit_ratio = difflib.SequenceMatcher(None, text_A, text_B).ratio()
    texts_differ = (1.0 - edit_ratio) > edit_threshold
    
    # Check intersecting tags or entities
    entities_A = extract_key_entities(text_A).union(set(sb_a.tags))
    entities_B = extract_key_entities(text_B).union(set(sb_b.tags))
    
    no_shared_entities = len(entities_A & entities_B) == 0
    
    # 5. Decision
    different_conclusion = texts_differ or no_shared_entities
    
    return different_conclusion

def check_conflict(new_sb: SessionBrief, ctx: SystemContext) -> bool:
    """Check for conflicting decisions in memory.
    
    Scans RAM index for matching similar sessions (cosine > 0.85).
    If a previous session is found that discusses the same topic but reaches
    a contradictory conclusion, flags both as conflicted.
    """
    if not ctx.hnsw_session or new_sb.embedding is None:
        return False
        
    vec = new_sb.embedding
    
    # Query nearest 10 via HNSW
    count = ctx.hnsw_session.get_current_count()
    if count == 0:
        return False
    k_to_query = min(10, count)
    
    try:
        labels, distances = ctx.hnsw_session.knn_query(vec.reshape(1, -1), k=k_to_query)
    except Exception as e:
        logger.warning(f"Failed HNSW knn_query for conflict check: {e}")
        return False
        
    # Ensure items exist
    if len(labels) == 0 or len(labels[0]) == 0:
        return False
        
    conflict_found = False
    
    for label, dist in zip(labels[0], distances[0]):
        cosine_sim = 1.0 - float(dist)
        if cosine_sim <= 0.85:
            continue
            
        sid = ctx.id_to_sid.get(int(label))
        if not sid or sid == new_sb.session_id:
            continue
            
        neighbor_sb = ctx.ram_index.get(sid)
        if not neighbor_sb:
            continue
            
        # Check importance bounds
        if neighbor_sb.importance in ("critical", "important") and new_sb.importance in ("critical", "important"):
            if decisions_contradict(new_sb, neighbor_sb, ctx.models.embedder):
                # Flag both sessions
                new_sb.conflict_flag = True
                neighbor_sb.conflict_flag = True
                
                logger.warning(f"Conflict detected between {new_sb.session_id} and {sid} (sim={cosine_sim:.2f})")
                conflict_found = True
                
    return conflict_found

async def tuner_check(entity: SessionBrief, ctx: SystemContext) -> SessionBrief:
    """Pass memory representation through Tuner checks before saving.
    
    Implements Conflict Detector (Phase 3). Semantic Drift, Anchor Validator,
    and Embedding Recalibrator are deferred to future patches.
    """
    start_ms = time.time() * 1000
    flags = []
    
    # 1. Conflict check (blocks dissolution if flagged)
    if check_conflict(entity, ctx):
        flags.append("conflict")
        
    
    return entity
