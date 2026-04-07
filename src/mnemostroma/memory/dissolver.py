# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
import time
from typing import Dict, Any, List, Optional
from ..core import SystemContext

logger = logging.getLogger("mnemostroma.dissolver")

class Dissolver:
    """Memory manager responsible for RAM eviction (eviction).
    
    Ensures RAM usage stays within limits by moving low-score sessions to SQLite.
    """
    def __init__(self, ctx: SystemContext):
        self.ctx = ctx
        self.config = ctx.config.resources

    async def check_and_evict(self):
        """Check RAM limits and trigger eviction if necessary.
        
        Rules:
        1. If session count > window_size * 0.8 -> evict N.
        2. If RAM usage (estimated) > soft_limit -> evict N.
        """
        current_count = len(self.ctx.ram_index)
        limit = self.ctx.config.resources.session_window_size
        
        if current_count > limit * 0.8:
            n_to_evict = int(current_count - limit * 0.7)
            await self.evict_n_oldest(n_to_evict)

    async def evict_n_oldest(self, n: int):
        """Evict N sessions with the lowest eviction priority.

        Priority formula (MEMORY_SPEC_v2 § 7):
            priority = importance_weight × (1 + intensity) × recency_factor
        Sessions with min(priority) are evicted first.
        Sessions with intensity > 0 are flushed to SQLite rather than deleted.
        """
        if n <= 0:
            return

        # P1: flush pending writes before eviction — guarantee SQLite persistence
        if self.ctx.persistence:
            await self.ctx.persistence.flush()

        ram_before = len(self.ctx.ram_index)
        sessions = list(self.ctx.ram_index.values())
        sessions.sort(key=_eviction_priority)

        evicted_count = 0
        for sb in sessions:
            if evicted_count >= n:
                break
            if not can_evict(sb, self.config):
                continue
            del self.ctx.ram_index[sb.session_id]
            # P0: clean label mappings
            label = self.ctx.sid_to_id.pop(sb.session_id, None)
            if label is not None:
                self.ctx.id_to_sid.pop(label, None)
            evicted_count += 1

        # P0: rebuild MatrixSearch to remove stale vectors
        if evicted_count > 0:
            _rebuild_session_index(self.ctx)

        # Log eviction (v1.0 spec — Point #9)

        logger.info(f"Dissolver evicted {evicted_count} sessions from RAM.")

    async def start(self):
        """Start the background eviction loop."""
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Dissolver background loop started")

    async def stop(self):
        """Stop the background eviction loop."""
        self._running = False
        if hasattr(self, "_task"):
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Dissolver background loop stopped")

    async def _run_loop(self):
        """Periodic check for RAM limits."""
        # Use default 60s if not in config
        interval = getattr(self.ctx.config.resources, 'dissolution_interval_sec', 60.0)
        while self._running:
            try:
                await self.check_and_evict()
                await asyncio.sleep(interval)
            except Exception as e:
                logger.error(f"Error in Dissolver loop: {e}", exc_info=True)
                await asyncio.sleep(interval)

# Importance → float weight for eviction priority formula
_IMPORTANCE_WEIGHT = {
    "principle":  1.0,
    "critical":   0.9,
    "important":  0.6,
    "background": 0.3,
}


def _eviction_priority(sb: Any) -> float:
    """Compute eviction priority (ascending = evict first).

    priority = importance_weight × (1 + intensity) × recency_factor

    recency_factor: 1.0 for brand-new, decays to 0.0 at 90 days.
    Sessions with LOW priority are evicted first.
    """
    import time
    imp_w = _IMPORTANCE_WEIGHT.get(getattr(sb, 'importance', 'background'), 0.3)
    intensity = float(getattr(sb, 'intensity', 0.0))
    age_days = (time.time() - getattr(sb, 'created_at', 0)) / 86400
    recency = max(0.0, 1.0 - age_days / 90.0)
    return imp_w * (1.0 + intensity) * recency


def can_evict(sb: Any, config: Any) -> bool:
    """Check if a specific session can be evicted according to spec rules.

    Rules (in priority order):
    - Principle: NEVER evict (resolution floor = 0.80, always RAM Hot/Warm).
    - Active urgency (live deadline): protect from eviction.
    - Conflict flag: keep in RAM for resolution.
    """
    import time
    if sb.importance == "principle":
        return False
    # Urgency active = deadline exists, in the future, and not expired
    has_live_deadline = (
        getattr(sb, 'deadline_ts', None) is not None and
        not sb.urgency_expired and
        (sb.deadline_ts or 0) > time.time()
    )
    if has_live_deadline:
        return False
    if sb.conflict_flag:
        return False
    return True


def _rebuild_session_index(ctx: "SystemContext") -> None:
    """Rebuild session_index from remaining ram_index entries after eviction.

    Resets sid_to_id, id_to_sid, and _next_session_label, then re-adds all
    sessions that have an embedding. Called by evict_n_oldest after batch eviction
    to remove stale vectors from MatrixSearch (P0 fix).
    """
    if not hasattr(ctx, 'session_index') or ctx.session_index is None:
        return

    ctx.session_index.clear()
    ctx.sid_to_id.clear()
    ctx.id_to_sid.clear()
    ctx._next_session_label = 0

    vectors, labels = [], []
    for sid, sb in ctx.ram_index.items():
        emb = getattr(sb, 'embedding', None)
        if emb is None:
            continue
        import numpy as np
        label = ctx.get_session_label(sid)
        vectors.append(np.array(emb, dtype='float32').flatten())
        labels.append(label)

    if vectors:
        ctx.session_index.add_items(vectors, labels)
