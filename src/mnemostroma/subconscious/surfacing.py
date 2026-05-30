# SPDX-License-Identifier: FSL-1.1-MIT
"""Associative Surfacing — involuntary memory surfacing (Phase 11.A).

Scans AnchorIndex and RAM SessionIndex using incoming message embedding.
Results delivered via ctx_active() surfaced field — no agent tool call needed.
Zero extra ONNX calls: reuses the embedding computed at Observer Step 1.
"""
import logging
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.subconscious.surfacing")


async def associative_scan(
    embedding: np.ndarray,
    ctx: "SystemContext",
    anchor_threshold: float = 0.75,
    session_threshold: float = 0.78,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Scan anchor and session indices for associatively related items.

    Reuses pre-computed embedding — zero extra ONNX calls.
    Returns list of surfaced items sorted by similarity desc.

    Args:
        embedding: Pre-computed message embedding (from Observer Step 1).
        ctx: System context with anchor_index and ram_index.
        anchor_threshold: Cosine threshold for anchor matches.
        session_threshold: Cosine threshold for session matches.
        max_results: Maximum items to surface.
    """
    results: list[dict[str, Any]] = []

    # 1. Scan AnchorIndex
    if ctx.anchor_index is not None:
        for anchor in ctx.anchor_index.anchors.values():
            if anchor.embedding is None:
                continue
            sim = float(np.dot(embedding, anchor.embedding))
            if sim >= anchor_threshold:
                results.append({
                    "type": "anchor",
                    "id": anchor.anchor_id,
                    "brief": anchor.brief,
                    "anchor_type": anchor.anchor_type,
                    "similarity": round(sim, 3),
                    "decay_level": anchor.decay_level,
                })

    # 2. Scan SessionIndex (RAM only)
    for sb in ctx.ram_index.values():
        if sb.embedding is None:
            continue
        sim = float(np.dot(embedding, sb.embedding))
        if sim >= session_threshold:
            results.append({
                "type": "session",
                "id": sb.session_id,
                "brief": sb.brief,
                "importance": sb.importance,
                "similarity": round(sim, 3),
                "created_at": sb.created_at,
            })

    # 3. Sort by similarity desc, deduplicate, limit
    results.sort(key=lambda x: x["similarity"], reverse=True)
    seen: set = set()
    deduped: list[dict[str, Any]] = []
    for r in results:
        rid = r["id"]
        if rid not in seen:
            seen.add(rid)
            deduped.append(r)

    return deduped[:max_results]


def _keyword_surface(text: str, ctx: "SystemContext") -> list[dict[str, Any]]:
    """Layer 1: fast keyword match of anchor briefs against incoming text.

    Catches obvious surfacing triggers in the same turn.
    Only checks constraint/principle/decision anchors to reduce noise.
    """
    anchor_index = getattr(ctx, "anchor_index", None)
    if anchor_index is None:
        return []

    text_lower = text.lower()
    hits: list[dict[str, Any]] = []

    for anchor in anchor_index.anchors.values():
        if anchor.anchor_type not in ("constraint", "principle", "decision"):
            continue
        words = [w for w in anchor.brief.lower().split() if len(w) > 4]
        if any(w in text_lower for w in words):
            hits.append({
                "type": "anchor",
                "id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": None,
                "layer": 1,
            })
    return hits[:3]
