# SPDX-License-Identifier: FSL-1.1-MIT
import time
from typing import Any

import numpy as np


def get_importance_weight(importance: str, ctx: Any) -> float:
    """Get the importance weight from config (γ signal)."""
    imp_map = {
        "background": ctx.config.importance.weight_background,
        "important": ctx.config.importance.weight_important,
        "critical": ctx.config.importance.weight_critical,
        "principle": ctx.config.importance.weight_principle,
    }
    return imp_map.get(importance, 0.1)


async def calculate_score(
    relevance: float,
    created_at: int,
    importance: str,
    ctx: Any,
    profile: str = "write",  # "write" or "search"
    urgency_expired: bool = False,
    implicit_score: float = 0.5,
) -> float:
    """Calculate ranking score using profile-based weights.

    Applies implicit feedback adjustment per feedback_loop_v1.5.md § 7:
        R_adjusted = R × (0.7 + 0.3 × implicit_score)
    At implicit_score=0.5 (neutral): R_adjusted = 0.85×R (non-destructive baseline).
    At implicit_score=1.0 (REVISIT): R_adjusted = R (full weight).
    At implicit_score=0.0 (IGNORE): R_adjusted = 0.7×R (naturally drifts to eviction).

    Profile A (Write): α=0.5, β=0.3, γ=0.2
    Profile B (Search): α=0.6, β=0.3, γ=0.1

    Args:
        relevance: Raw relevance score from HNSW/reranker (0.0–1.0).
        created_at: Session creation Unix timestamp.
        importance: Level: background / important / critical / principle.
        ctx: System context (for config access).
        profile: Scoring profile — "write" or "search".
        urgency_expired: Apply 50% penalty if deadline has passed.
        implicit_score: EMA-adjusted feedback score (0.0–1.0), default 0.5 neutral.

    Returns:
        float: Final composite score.
    """
    # Temporal decay (architecture_overview.md § 5)
    age_days = (time.time() - created_at) / 86400
    T = np.exp(-ctx.config.score.temporal_decay_lambda * age_days)

    # Importance weights (γ signal)
    I = get_importance_weight(importance, ctx)

    # Adjust relevance by implicit feedback (feedback_loop_v1.5.md § 7)
    r_adjusted = relevance * (0.7 + 0.3 * implicit_score)

    if profile == "search":
        # Search Profile (architecture_patch_v1.4.md)
        alpha, beta, gamma = 0.6, 0.3, 0.1
    else:
        # Write Profile
        alpha, beta, gamma = 0.5, 0.3, 0.2

    score = alpha * r_adjusted + beta * T + gamma * I

    # v1.3 Quiet Behaviors (Policy modifiers)
    if urgency_expired:
        score *= 0.50  # URGENCY_EXPIRED_PENALTY
    if importance == "principle":
        score *= 1.30  # PRINCIPLE_BOOST

    return score
