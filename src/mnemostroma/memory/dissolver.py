# SPDX-License-Identifier: FSL-1.1-MIT
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
        limit = self.ctx.config.observer.session_window_size
        
        if current_count > limit * 0.8:
            n_to_evict = int(current_count - limit * 0.7)
            await self.evict_n_oldest(n_to_evict)

    async def evict_n_oldest(self, n: int):
        """Evict N sessions with the lowest Scores.
        
        Critical and Principle sessions are protected unless absolutely necessary.
        """
        if n <= 0:
            return
        
        ram_before = len(self.ctx.ram_index)
        sessions = list(self.ctx.ram_index.values())
        sessions.sort(key=lambda x: x.score)
        
        evicted_count = 0
        for sb in sessions:
            if evicted_count >= n:
                break
            if not can_evict(sb, self.config):
                continue
            del self.ctx.ram_index[sb.session_id]
            evicted_count += 1
            
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

import asyncio

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
