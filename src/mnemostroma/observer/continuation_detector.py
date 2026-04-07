# SPDX-License-Identifier: FSL-1.1-MIT
"""B.2 Continuation Detector — full scoring formula.

score = cosine × 0.7 + tag_overlap × 0.1 + recency × 0.2

Three outcomes:
  continuation — combined score ≥ continuation_score_threshold (default 0.65)
  related      — cosine ≥ related_cosine_threshold (default 0.45), below continuation
  new          — neither

Pipeline integration:
    result = detect_continuation(embedding, tags, ctx)
    is_new_entity   = result["state"] == "new"
    continuation_of = result["continuation_of"]
    continuation_depth = result["continuation_depth"]
"""
import logging
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import numpy as np

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.continuation_detector")

# Weight constants
_W_COSINE  = 0.7
_W_TAGS    = 0.1
_W_RECENCY = 0.2


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity in [0, 1] between two float32 vectors."""
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _tag_overlap(tags_a: List[str], tags_b: List[str]) -> float:
    """Jaccard overlap between two tag lists, clamped to [0, 1]."""
    if not tags_a or not tags_b:
        return 0.0
    set_a, set_b = set(tags_a), set(tags_b)
    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union if union else 0.0


def _recency_score(created_at: int, max_age_days: int) -> float:
    """Linear decay from 1.0 (just created) to 0.0 (max_age_days old)."""
    age_days = (time.time() - created_at) / 86400
    if age_days >= max_age_days:
        return 0.0
    return 1.0 - (age_days / max_age_days)


def _chain_depth(sid: str, ctx: "SystemContext", visited: Optional[set] = None) -> int:
    """Trace continuation chain depth via anchor_index, with circular-chain protection."""
    if visited is None:
        visited = set()
    if sid in visited or not ctx.anchor_index:
        return 0
    visited.add(sid)
    anchor = ctx.anchor_index.get(sid)
    if not anchor:
        return 0
    parent = anchor.flags.get("continuation_of")
    if not parent or parent == sid:
        return 0
    return 1 + _chain_depth(parent, ctx, visited)


def detect_continuation(
    current_embedding: np.ndarray,
    current_tags: List[str],
    ctx: "SystemContext",
    max_lookback: int = 10,
    continuation_score_threshold: float = 0.65,
    related_cosine_threshold: float = 0.45,
    max_age_days: int = 7,
) -> Dict[str, Any]:
    """Full B.2 continuation detection.

    Steps:
    1. index top-K search (inside caller's index_lock).
    2. Filter candidates by age (> max_age_days → skip).
    3. For each candidate: combined_score = cosine×0.7 + tag_overlap×0.1 + recency×0.2.
    4. Pick best candidate.
    5. Classify: continuation / related / new.
    6. Trace chain depth.

    Args:
        current_embedding: float32 vector of the current session.
        current_tags: tag list of the current session.
        ctx: active SystemContext (index_lock must be held by caller).
        max_lookback: how many HNSW neighbours to examine.
        continuation_score_threshold: min combined score for "continuation".
        related_cosine_threshold: min cosine for "related" (below continuation).
        max_age_days: sessions older than this are excluded from candidates.

    Returns:
        dict with keys:
            state            — "continuation" | "related" | "new"
            continuation_of  — session_id of best match (or None)
            continuation_depth — chain depth (0 for new/related)
            best_score       — combined score of winner (0.0 if new)
            best_cosine      — raw cosine of winner (0.0 if new)
            candidates_count — how many candidates were evaluated
    """
    null_result: Dict[str, Any] = {
        "state": "new",
        "continuation_of": None,
        "continuation_depth": 0,
        "best_score": 0.0,
        "best_cosine": 0.0,
        "candidates_count": 0,
    }

    if not ctx.session_index or ctx.session_index.get_current_count() == 0:
        return null_result

    vec_f32 = current_embedding.astype(np.float32).flatten()
    k = min(max_lookback, ctx.session_index.get_current_count())

    try:
        labels, distances = ctx.session_index.knn_query(vec_f32, k=k)
    except Exception as e:
        logger.error(f"continuation_detector: HNSW query failed: {e}")
        return null_result

    # distances are cosine *distances* (1 - similarity) — MatrixSearch convention
    now = time.time()
    best_score = 0.0
    best_cosine = 0.0
    best_sid: Optional[str] = None
    evaluated = 0

    for label, dist in zip(labels, distances):
        sid = ctx.id_to_sid.get(int(label))
        if not sid:
            continue

        cosine = max(0.0, 1.0 - float(dist))  # convert distance → similarity

        # Age filter
        sb = ctx.ram_index.get(sid)
        if sb is None:
            continue
        age_days = (now - sb.created_at) / 86400
        if age_days > max_age_days:
            continue

        evaluated += 1

        tag_sim  = _tag_overlap(current_tags, getattr(sb, 'tags', []))
        recency  = _recency_score(sb.created_at, max_age_days)
        combined = _W_COSINE * cosine + _W_TAGS * tag_sim + _W_RECENCY * recency

        if combined > best_score:
            best_score  = combined
            best_cosine = cosine
            best_sid    = sid

    result = {**null_result, "candidates_count": evaluated,
              "best_score": round(best_score, 4),
              "best_cosine": round(best_cosine, 4)}

    if best_sid is None:
        return result

    # Classify
    if best_score >= continuation_score_threshold:
        depth = _chain_depth(best_sid, ctx) + 1
        result.update({
            "state": "continuation",
            "continuation_of": best_sid,
            "continuation_depth": depth,
        })
    elif best_cosine >= related_cosine_threshold:
        result.update({
            "state": "related",
            "continuation_of": best_sid,  # kept for reference, not a true chain
            "continuation_depth": 0,
        })

    return result
