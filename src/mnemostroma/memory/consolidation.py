# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import time
import logging
from typing import Any, Optional, List
from ..memory.scoring import calculate_score

logger = logging.getLogger("mnemostroma.consolidation")

class ConsolidationWorker:
    """Background worker for offline memory maintenance.
    
    Tasks:
    1. Recalculate Scores for all RAM sessions.
    2. Update age_signal (fresh -> actual -> stale -> archive).
    3. Check expired deadlines (v1.3).
    4. Trigger Dissolver eviction.
    """
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._running = False
        self._task = None

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("ConsolidationWorker started.")

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("ConsolidationWorker stopped.")

    async def _run(self):
        # Use dissolver's consolidation_interval_sec from config
        interval = self.ctx.config.dissolver.consolidation_interval_sec
        while self._running:
            try:
                await asyncio.sleep(interval)
                await self.consolidate()
            except Exception as e:
                logger.error(f"Error in ConsolidationWorker: {e}", exc_info=True)

    async def consolidate(self):
        """Main consolidation loop."""
        now = time.time()
        
        # 1. Update Age Signal and Deadlines
        for sid, sb in list(self.ctx.ram_index.items()):
            age_days = (now - sb.created_at) / 86400
            
            # Update signal
            if age_days > 90: sb.age_signal = "archive"
            elif age_days > 30: sb.age_signal = "stale"
            elif age_days > 7: sb.age_signal = "actual"
            else: sb.age_signal = "fresh"
            
            # Check deadlines (v1.3)
            if sb.deadline_ts and sb.deadline_ts < now and not sb.urgency_expired:
                sb.urgency_expired = True
                logger.warning(f"Deadline expired for session {sid}")

        # 2. Recalculate Scores
        # We use background relevance (0.5) if not currently searching
        for sid, sb in self.ctx.ram_index.items():
            sb.score = await calculate_score(0.5, sb.created_at, sb.importance, self.ctx)

        # 2.5 Log Recalc (v1.0 spec — Point #8)

        # 3. Trigger Dissolver
        if hasattr(self.ctx, 'dissolver') and self.ctx.dissolver:
            await self.ctx.dissolver.check_and_evict()
            
        logger.info(f"Consolidation completed for {len(self.ctx.ram_index)} RAM sessions.")
