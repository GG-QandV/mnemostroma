# SPDX-License-Identifier: FSL-1.1-MIT
import difflib
import logging
import time
from typing import Any

import numpy as np

from ..core import SystemContext
from ..memory.session_index import SessionBrief

logger = logging.getLogger("mnemostroma.tuner")

def extract_key_entities(text: str) -> set[str]:
    """Simplified NER: extracts potential nouns and named entities."""
    import re
    return set(re.sub(r'[^\w]', '', t).lower()
               for t in text.split()
               if len(re.sub(r'[^\w]', '', t)) > 4)

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
    
    # 5. Decision — same topic (cosine ≥ 0.85 already guaranteed by caller) + different conclusion
    # texts_differ: wording diverges enough
    # no_shared_entities: no literal token overlap (e.g. "PostgreSQL" vs "MongoDB")
    # Either condition is sufficient: truly contradictory sessions may differ in wording
    # OR use completely different terminology (same semantic space, different tokens)
    different_conclusion = texts_differ or no_shared_entities

    return different_conclusion

def check_conflict(new_sb: SessionBrief, ctx: SystemContext) -> bool:
    """Check for conflicting decisions in memory.

    Scans RAM index for matching similar sessions (cosine > 0.85).
    If a previous session is found that discusses the same topic but reaches
    a contradictory conclusion, flags both as conflicted.

    Logs detailed analysis including:
    - Index state (count, k_to_query)
    - Similarity scores of all neighbors
    - Entities comparison
    - Final conflict determination
    """
    if not ctx.session_index or new_sb.embedding is None:
        logger.debug(f"check_conflict skip: no index or embedding for {new_sb.session_id}")
        return False

    vec = new_sb.embedding

    # Query nearest 10 via HNSW
    count = ctx.session_index.get_current_count()
    if count == 0:
        logger.debug(f"check_conflict skip: index empty for {new_sb.session_id}")
        return False
    k_to_query = min(10, count)

    try:
        labels, distances = ctx.session_index.knn_query(vec.reshape(1, -1), k=k_to_query)
    except Exception as e:
        logger.warning(f"Failed HNSW knn_query for conflict check: {e}")
        return False

    # Ensure items exist
    if not labels:
        logger.debug(f"check_conflict: no neighbors found for {new_sb.session_id}")
        return False

    # Log neighbor analysis
    neighbors_analyzed = []
    conflict_found = False

    for label, dist in zip(labels, distances):
        cosine_sim = 1.0 - float(dist)

        neighbor_info = {
            "similarity": round(cosine_sim, 4),
            "passed_threshold": cosine_sim > 0.85,
        }

        if cosine_sim <= 0.85:
            neighbors_analyzed.append(neighbor_info)
            continue

        sid = ctx.id_to_sid.get(int(label))
        if not sid or sid == new_sb.session_id:
            neighbor_info["skipped_reason"] = "self_reference" if sid == new_sb.session_id else "no_mapping"
            neighbors_analyzed.append(neighbor_info)
            continue

        neighbor_sb = ctx.ram_index.get(sid)
        if not neighbor_sb:
            neighbor_info["skipped_reason"] = "not_in_ram"
            neighbors_analyzed.append(neighbor_info)
            continue

        neighbor_info["neighbor_id"] = sid
        neighbor_info["neighbor_importance"] = neighbor_sb.importance
        neighbor_info["new_importance"] = new_sb.importance

        # Check importance bounds
        if neighbor_sb.importance in ("critical", "important") and new_sb.importance in ("critical", "important"):
            if decisions_contradict(new_sb, neighbor_sb, ctx.models.embedder):
                # Flag both sessions
                new_sb.conflict_flag = True
                neighbor_sb.conflict_flag = True

                neighbor_info["contradicts"] = True
                logger.warning(f"Conflict detected between {new_sb.session_id} and {sid} (sim={cosine_sim:.2f})")
                conflict_found = True
            else:
                neighbor_info["contradicts"] = False
        else:
            neighbor_info["skipped_reason"] = "importance_mismatch"

        neighbors_analyzed.append(neighbor_info)

    # Log analysis results
    logger.debug(f"Conflict check {new_sb.session_id}: {len(neighbors_analyzed)} neighbors, conflict={conflict_found}")

    return conflict_found

async def tuner_check(entity: SessionBrief, ctx: SystemContext) -> SessionBrief:
    """Pass memory representation through Tuner checks before saving.

    Implements Conflict Detector (Phase 3). Semantic Drift, Anchor Validator,
    and Embedding Recalibrator are deferred to future patches.
    """
    start_ms = time.time() * 1000
    flags = []
    analysis_data = {
        "session_id": entity.session_id,
        "importance": entity.importance,
        "brief": entity.brief[:100] if entity.brief else "",
        "tags": entity.tags,
        "has_embedding": entity.embedding is not None,
    }

    # Log START of check
    if hasattr(ctx, "log_writer") and ctx.log_writer:
        pass

    # 1. Conflict check (blocks dissolution if flagged)
    conflict_details = {}
    if check_conflict(entity, ctx):
        flags.append("conflict")
        conflict_details["detected"] = True
    else:
        conflict_details["detected"] = False

    latency = (time.time() * 1000) - start_ms

    # Log RESULT of check with full details
    if hasattr(ctx, "log_writer") and ctx.log_writer:
        result_data = {
            "detected": bool(flags),
            "flags": flags,
            "session_id": entity.session_id,
            "importance": entity.importance,
            "conflict_details": conflict_details,
            "embedding_available": entity.embedding is not None,
            "latency_ms": round(latency, 2),
        }

    return entity
