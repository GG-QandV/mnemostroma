# SPDX-License-Identifier: FSL-1.1-MIT
"""Session Bridge — ctx.sync() and ctx.load().

ctx_sync():  Force-flush RAM→SQLite, WAL checkpoint, return stats.
ctx_load():  Lazy-load a specific session from cold SQLite into RAM.
"""
import logging
from typing import Any

import numpy as np

from ..core import SystemContext

logger = logging.getLogger("mnemostroma.bridge")


async def ctx_sync(ctx: SystemContext, checkpoint_mode: str = "PASSIVE") -> dict[str, Any]:
    """Force immediate flush of all pending RAM changes to SQLite.

    Steps:
    1. Drain persistence queue (wait until all put_nowait items are persisted).
    2. WAL checkpoint (PASSIVE by default; caller passes TRUNCATE on shutdown).
    3. Return stats: flushed_sessions, wal_pages.

    Args:
        ctx: Active SystemContext.
        checkpoint_mode: "PASSIVE" (non-blocking) or "TRUNCATE" (graceful shutdown).

    Returns:
        dict with keys flushed_sessions, wal_pages, checkpoint_mode.
    """
    if not ctx.persistence:
        return {"flushed_sessions": 0, "wal_pages": -1, "checkpoint_mode": checkpoint_mode}

    return await ctx.persistence.sync(checkpoint_mode=checkpoint_mode)


async def ctx_load(session_id: str, ctx: SystemContext) -> Any | None:
    """Force-load a specific session from SQLite cold storage into RAM.

    Steps:
    1. RAM hit → return immediately (no-op).
    2. SQLite SELECT by session_id → deserialize into SessionBrief.
    3. Add embedding to session_index (inside index_lock).
    4. Evict lowest-score session if session_window full.
    5. Return SessionBrief or None.

    Args:
        session_id: ID of the session to load.
        ctx: Active SystemContext.

    Returns:
        SessionBrief if found, else None.
    """
    # 1. RAM hit
    if session_id in ctx.ram_index:
        return ctx.ram_index[session_id]

    # 2. Cold load from SQLite
    if not ctx.persistence:
        return None

    sb = await ctx.persistence.get_session_by_id(session_id)
    if sb is None:
        return None

    # 3. Evict if RAM window full
    window_size = ctx.config.resources.session_window_size
    if len(ctx.ram_index) >= window_size:
        _evict_lowest_score(ctx)

    # 4. Add embedding to session index (atomic)
    if sb.embedding is not None and ctx.session_index:
        vec_f32 = np.array(sb.embedding, dtype=np.float32).flatten()
        async with ctx.index_lock:
            label = ctx.get_session_label(session_id)
            ctx.session_index.add_items([vec_f32], [label])
            ctx.id_to_sid[label] = session_id
            ctx.sid_to_id[session_id] = label

    # 5. Hot-load into RAM
    ctx.ram_index[session_id] = sb

    logger.debug(f"ctx_load: session {session_id} loaded from cold storage")
    return sb


def _evict_lowest_score(ctx: SystemContext) -> None:
    """Remove the lowest-score non-pinned session from RAM to make room."""
    if not ctx.ram_index:
        return

    # Sort by score ascending, skip user-pinned anchors
    def _evict_score(item):
        sid, sb = item
        anchor = ctx.anchor_index.get(sid) if ctx.anchor_index else None
        if anchor and anchor.flags.get("user_pin"):
            return float("inf")  # protected
        return getattr(sb, "score", 0.0)

    victim_sid = min(ctx.ram_index.items(), key=_evict_score)[0]
    del ctx.ram_index[victim_sid]
    logger.debug(f"ctx_load evict: removed session {victim_sid} from RAM")
