# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import ctypes
import gc
import time
import logging
from typing import Any, Optional, List
from pathlib import Path
from ..memory.scoring import calculate_score

_CONS_BUILD_TAG_ = ""  # consolidation build tag

logger = logging.getLogger("mnemostroma.consolidation")

# key_facts budget per decay level (spec: full→partial→skeleton→bedrock)
_DECAY_FACTS_LIMIT = {0: 5, 1: 3, 2: 1, 3: 0}


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
        self._last_anchor_decay: float = 0.0

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
        interval = self.ctx.config.dissolver.consolidation_interval_sec
        _retention_interval = 86400  # cleanup logs once per 24h
        _last_retention = time.time()
        self._snapshot_tick = getattr(self, '_snapshot_tick', 0)
        while self._running:
            try:
                await asyncio.sleep(interval)
                
                # --- db_snapshots: record DB sizes every hour (every 12 ticks × 300s) ---
                self._snapshot_tick += 1
                if self._snapshot_tick % 12 == 0:
                    try:
                        _mnemo_dir  = Path.home() / ".mnemostroma"
                        _db_mb      = (_mnemo_dir / "mnemostroma.db").stat().st_size / 1_048_576 \
                                      if (_mnemo_dir / "mnemostroma.db").exists() else 0.0
                        _logs_mb    = (_mnemo_dir / "logs.db").stat().st_size / 1_048_576 \
                                      if (_mnemo_dir / "logs.db").exists() else 0.0
                        if hasattr(self.ctx, 'log_writer') and self.ctx.log_writer:
                            await self.ctx.log_writer.snapshot_db_sizes(_db_mb, _logs_mb)
                    except Exception:
                        pass  # snapshots are non-critical, never crash the worker
                # --- end db_snapshots ---
                
                await self.consolidate()
                # Log retention: delete entries older than 30 days
                if time.time() - _last_retention >= _retention_interval:
                    if hasattr(self.ctx, 'log_writer') and self.ctx.log_writer:
                        await self.ctx.log_writer.cleanup(retention_days=30)
                    _last_retention = time.time()
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

        # 4. Experience Decay Engine
        if (getattr(self.ctx, 'experience_index', None)
                and self.ctx.config.experience.layer_enabled):
            threshold = self.ctx.config.experience.exp_decay_days_threshold
            rate = self.ctx.config.experience.exp_decay_rate
            decayed_tags = self.ctx.experience_index.apply_decay(threshold, rate)
            if decayed_tags and self.ctx.persistence:
                for tag in decayed_tags:
                    cluster = self.ctx.experience_index.get(tag)
                    if cluster:
                        await self.ctx.persistence.save_experience(
                            tag=cluster.tag,
                            session_count=cluster.session_count,
                            score_sum=cluster.score_sum,
                            conflict_count=cluster.conflict_count,
                            last_updated=cluster.last_updated,
                            emotion_positive=cluster.emotion_positive,
                            emotion_negative=cluster.emotion_negative,
                            emotion_intensity_sum=cluster.emotion_intensity_sum,
                        )

        # 5. Anchor Decay Engine
        cfg_ad = getattr(self.ctx.config, 'anchor_decay', None)
        if cfg_ad and cfg_ad.enabled:
            interval_sec = cfg_ad.interval_min * 60
            if now - self._last_anchor_decay >= interval_sec:
                decayed = await self._run_anchor_decay(now)
                self._last_anchor_decay = now
                if decayed:

        # Release fragmented Python heap pages back to OS
        gc.collect()
        try:
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass

        logger.info(f"Consolidation completed for {len(self.ctx.ram_index)} RAM sessions.")

    async def _run_anchor_decay(self, now: float) -> int:
        """Advance decay_level for inactive, unpinned anchors.

        Decay levels:
          0 = full    (key_facts ≤ 5)
          1 = partial (key_facts ≤ 3)
          2 = skeleton (key_facts ≤ 1)
          3 = bedrock (key_facts = 0, brief only — anchor never deleted)

        Trigger: days_since_last_access >= threshold_days AND NOT user_pin
        """
        if not getattr(self.ctx, 'anchor_index', None):
            return 0

        cfg = self.ctx.config.anchor_decay
        decayed = 0

        for anchor in self.ctx.anchor_index.all():
            if anchor.flags.get("user_pin"):
                continue
            if anchor.decay_level >= 3:
                continue

            last_access = anchor.last_accessed_at or anchor.created_at
            days_inactive = (now - last_access) / 86400

            if days_inactive < cfg.threshold_days:
                continue

            # Advance one level at a time
            anchor.decay_level = min(3, anchor.decay_level + 1)
            anchor.updated_at = int(now)

            # Trim key_facts to budget for new level
            limit = _DECAY_FACTS_LIMIT[anchor.decay_level]
            if len(anchor.key_facts) > limit:
                anchor.key_facts = anchor.key_facts[:limit]

            # Persist change to SQLite
            if self.ctx.persistence:
                await self.ctx.persistence.save_anchor(anchor)

            logger.debug(
                "anchor.decay | id=%s level=%d facts=%d inactive_days=%.1f",
                anchor.anchor_id, anchor.decay_level,
                len(anchor.key_facts), days_inactive,
            )
            decayed += 1

        return decayed
