# SPDX-License-Identifier: FSL-1.1-MIT
"""Anchor Guardian — subconscious constraint checker (Phase 11.C).

Scans incoming message embedding against load-bearing anchors.
Fires automatically in Observer Step 1.5 — no agent tool call needed.
Zero extra ONNX calls: reuses the embedding computed at Step 1.
"""
import logging
import time
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.subconscious.guardian")

GUARDIAN_TYPES = {"principle", "constraint", "critical", "decision"}


async def anchor_guardian(
    embedding: np.ndarray,
    ctx: "SystemContext",
    threshold: float = 0.72,
    cooldown_sec: float = 3600.0,
) -> list[dict[str, Any]]:
    """Check incoming message embedding against load-bearing anchors.

    Returns list of conflict warnings. Empty list = no conflicts.
    Zero extra ONNX calls — reuses Observer step 1 embedding.

    Args:
        embedding: Pre-computed message embedding (from Observer Step 1).
        ctx: System context with anchor_index.
        threshold: Cosine similarity threshold for conflict detection.
        cooldown_sec: Seconds before the same anchor can warn again.
    """
    if ctx.anchor_index is None:
        return []

    now = time.time()
    warnings: list[dict[str, Any]] = []

    for anchor in ctx.anchor_index.anchors.values():
        # Filter: only load-bearing types
        if anchor.anchor_type not in GUARDIAN_TYPES:
            continue
        # Filter: decayed decisions skipped
        if anchor.anchor_type == "decision" and anchor.decay_level > 0:
            continue
        # Filter: no embedding → skip
        if anchor.embedding is None:
            continue
        # Cooldown: skip if warned recently
        last_warned = ctx.recently_warned.get(anchor.anchor_id, 0)
        if now - last_warned < cooldown_sec:
            continue

        sim = float(np.dot(embedding, anchor.embedding))
        if sim >= threshold:
            warnings.append({
                "anchor_id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "set_at": anchor.created_at,
                "similarity": round(sim, 3),
                "decay_level": anchor.decay_level,
                "layer": 2,
            })
            ctx.recently_warned[anchor.anchor_id] = now

    warnings.sort(key=lambda x: x["similarity"], reverse=True)
    return warnings


def _keyword_anchor_check(text: str, ctx: "SystemContext") -> list[dict[str, Any]]:
    """Layer 1: fast keyword match against anchor briefs. Same-turn detection.

    Catches obvious conflicts immediately without waiting for Observer async scan.
    False positives acceptable — Layer 2 corrects next turn.

    Args:
        text: Raw user/agent message text.
        ctx: System context with anchor_index and recently_warned.
    """
    anchor_index = getattr(ctx, "anchor_index", None)
    if anchor_index is None:
        return []

    text_lower = text.lower()
    hits: list[dict[str, Any]] = []
    now = time.time()
    cooldown = getattr(ctx.config.anchor_guardian, "cooldown_sec", 3600.0)
    recently_warned = getattr(ctx, "recently_warned", {})

    for anchor in anchor_index.anchors.values():
        if anchor.anchor_type not in GUARDIAN_TYPES:
            continue
        last_warned = recently_warned.get(anchor.anchor_id, 0)
        if now - last_warned < cooldown:
            continue
        # Only words longer than 4 chars to reduce noise
        words = [w for w in anchor.brief.lower().split() if len(w) > 4]
        if any(w in text_lower for w in words):
            hits.append({
                "anchor_id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": None,
                "layer": 1,
                "set_at": anchor.created_at,
            })
            # Update recently_warned so this anchor won't repeat on next ctx_active() call
            if hasattr(ctx, "recently_warned"):
                ctx.recently_warned[anchor.anchor_id] = now

    return hits[:3]


async def scan_open_loops(
    embedding: np.ndarray,
    ctx: "SystemContext",
    threshold: float = 0.75,
    cooldown_sec: float = 7200.0,
    max_results: int = 5,
) -> list[dict[str, Any]]:
    """Phase 11.E: Semantic scan for pending-outcome anchors (open loops).

    Reuses Observer Step 1 embedding — zero extra ONNX calls.
    Filters: anchor_type in {decision, constraint} AND flags.outcome == "pending".
    Cooldown via ctx.recently_looped (separate from recently_warned).

    Args:
        embedding: Pre-computed message embedding (from Observer Step 1).
        ctx: System context with anchor_index and recently_looped.
        threshold: Cosine similarity threshold.
        cooldown_sec: Seconds before same anchor can resurface.
        max_results: Max open loops returned.
    """
    if ctx.anchor_index is None:
        return []

    now = time.time()
    hits: list[dict[str, Any]] = []
    recently_looped = getattr(ctx, "recently_looped", {})

    for anchor in ctx.anchor_index.anchors.values():
        if anchor.anchor_type != "decision":
            continue
        outcome = anchor.flags.get("outcome", "pending")
        if outcome != "pending":
            continue
        if anchor.embedding is None:
            continue
        last_looped = recently_looped.get(anchor.anchor_id, 0)
        if now - last_looped < cooldown_sec:
            continue

        sim = float(np.dot(embedding, anchor.embedding))
        if sim >= threshold:
            hits.append({
                "anchor_id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "set_at": anchor.created_at,
                "similarity": round(sim, 3),
                "decay_level": anchor.decay_level,
            })

    hits.sort(key=lambda x: x["similarity"], reverse=True)
    result = hits[:max_results]
    # Update cooldown only for anchors that will actually be returned
    for h in result:
        recently_looped[h["anchor_id"]] = now
    return result


def _keyword_open_loop(
    text: str,
    ctx: "SystemContext",
    cooldown_sec: float = 7200.0,
) -> list[dict[str, Any]]:
    """Layer 1: fast keyword match for pending-outcome anchors (open loops).

    Same-turn detection without waiting for Observer async scan.
    Only decision/constraint types with outcome == "pending".
    """
    anchor_index = getattr(ctx, "anchor_index", None)
    if anchor_index is None:
        return []

    text_lower = text.lower()
    hits: list[dict[str, Any]] = []
    now = time.time()
    recently_looped = getattr(ctx, "recently_looped", {})
    cooldown = cooldown_sec

    for anchor in anchor_index.anchors.values():
        if anchor.anchor_type != "decision":
            continue
        outcome = anchor.flags.get("outcome", "pending")
        if outcome != "pending":
            continue
        last_looped = recently_looped.get(anchor.anchor_id, 0)
        if now - last_looped < cooldown:
            continue
        words = [w for w in anchor.brief.lower().split() if len(w) > 4]
        if any(w in text_lower for w in words):
            hits.append({
                "anchor_id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": None,
                "set_at": anchor.created_at,
            })
            recently_looped[anchor.anchor_id] = now

    return hits[:3]


def _merge_warnings(
    layer1: list[dict[str, Any]],
    layer2: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge Layer 1 (keyword) and Layer 2 (semantic) warnings, dedup by anchor_id.

    Layer 2 entry wins if same anchor_id appears in both (has similarity score).
    """
    merged: dict[str, dict[str, Any]] = {}
    for w in layer1:
        merged[w["anchor_id"]] = w
    for w in layer2:
        merged[w["anchor_id"]] = w  # layer 2 overwrites layer 1
    return sorted(merged.values(), key=lambda x: x.get("similarity") or 0, reverse=True)
