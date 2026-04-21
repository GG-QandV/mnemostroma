# SPDX-License-Identifier: FSL-1.1-MIT
"""Dreamer — background anchor reassessment during idle periods (Stage D).

Activates when Conductor.is_idle() returns True.
Iterates over AnchorIndex, reassesses outcome flags, resurfaces high-access anchors.

Roadmap: Phase 4.1 (idle detection) + 4.2 (dreamer worker).
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from ..core import SystemContext
    from ..subconscious.anchor import Anchor

logger = logging.getLogger("mnemostroma.dreamer")


class Dreamer:
    """Idle-triggered anchor reassessment worker.

    Lifecycle: started by Conductor after bootstrap, runs a background loop
    polling `conductor.is_idle()`. When idle, runs one reassessment cycle.
    """

    def __init__(self, conductor: "object", ctx: "SystemContext"):
        self._conductor = conductor
        self._ctx = ctx
        self._running = False
        self._task: Optional[asyncio.Task] = None
        # Phase 2 — disk scan state (RAM-only, resets to 0 on daemon restart — intentional)
        self._disk_offset: int = 0
        self._disk_window: int = 1000
        self._disk_pass_resolved: int = 0  # T4 fix: counts resolutions per full pass

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        logger.info("Dreamer started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Dreamer stopped.")

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    async def _run(self) -> None:
        """Poll for idle state; run a dream cycle when idle."""
        poll_sec = 60  # check every minute
        while self._running:
            try:
                await asyncio.sleep(poll_sec)
                if self._conductor.is_idle():
                    await self.dream()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Dreamer._run error: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # Dream cycle
    # ------------------------------------------------------------------

    async def dream(self) -> dict:
        """One reassessment cycle over AnchorIndex.

        Steps:
        1. Collect candidate anchors (high access_count or pending outcome).
        2. Reassess outcome flag from recent RAM context.
        3. Resurface high-access anchors (log + touch).
        4. Return stats dict.
        """
        if not self._ctx.anchor_index:
            return {"anchors_checked": 0}

        cfg = getattr(self._ctx.config, 'dreamer', None)
        max_anchors = cfg.max_anchors_per_cycle if cfg else 20

        start = time.time()
        stats = {
            "anchors_checked": 0,
            "outcomes_updated": 0,
            "resurfaced": 0,
            "disk_anchors_checked": 0,
            "disk_outcomes_updated": 0,
        }

        # Sort by access_count desc — most-referenced anchors first
        candidates = sorted(
            self._ctx.anchor_index.all(),
            key=lambda a: a.access_count,
            reverse=True,
        )[:max_anchors]

        for anchor in candidates:
            stats["anchors_checked"] += 1

            # 2. Reassess outcome
            if self._reassess_outcome(anchor):
                stats["outcomes_updated"] += 1
                anchor.updated_at = int(time.time())
                if self._ctx.persistence:
                    await self._ctx.persistence.save_anchor(anchor)

            # 3. Resurface anchors with high access_count
            if anchor.access_count >= 3 and anchor.decay_level < 3:
                anchor.touch()
                stats["resurfaced"] += 1
                logger.debug(
                    "dreamer.resurface | id=%s type=%s access=%d",
                    anchor.anchor_id, anchor.anchor_type, anchor.access_count,
                )

        # Phase 2 — disk scan (pending anchors evicted from RAM by dissolver)
        disk_cfg = getattr(self._ctx.config, "dreamer", None)
        disk_enabled = getattr(disk_cfg, "disk_scan_enabled", True)
        if self._ctx.persistence and self._ctx.config and disk_enabled:
            disk_stats = await self._disk_scan()
            stats["disk_anchors_checked"] = disk_stats.get("disk_anchors_checked", 0)
            stats["disk_outcomes_updated"] = disk_stats.get("disk_outcomes_updated", 0)

        stats["duration_ms"] = round((time.time() - start) * 1000, 1)

        from ..storage.log_writer import log_event
        await log_event(self._ctx, "dreamer.cycle", "complete", stats)

        logger.info(
            "Dreamer cycle: checked=%d outcomes_updated=%d resurfaced=%d",
            stats["anchors_checked"], stats["outcomes_updated"], stats["resurfaced"],
        )
        return stats

    # ------------------------------------------------------------------
    # Phase 2 — Disk scan (iterative deepening)
    # ------------------------------------------------------------------

    async def _disk_scan(self) -> dict:
        """Scan SQLite for pending-outcome anchors not present in RAM.

        Strategy: iterative deepening with pagination.
        - Fetches one PAGE_SIZE page of multi-session+pending anchors per cycle.
        - Advances _disk_offset by PAGE_SIZE each call.
        - Resets _disk_offset to 0 when a page returns empty (full pass done).
        - Expands _disk_window x3 (up to 6000) when a full pass yields 0 resolutions.
        - _disk_pass_resolved tracks resolutions within the current pass (T4 fix).

        Returns:
            dict with disk_anchors_checked and disk_outcomes_updated.
        """
        PAGE_SIZE = getattr(
            getattr(self._ctx.config, "dreamer", None), "disk_scan_page_size", 50
        )
        stats = {"disk_anchors_checked": 0, "disk_outcomes_updated": 0}

        anchors = await self._ctx.persistence.find_anchors_by_flags(
            outcome="pending",
            multi_session=True,
            decay_level_max=2,
            limit=PAGE_SIZE,
            offset=self._disk_offset,
        )

        if not anchors:
            # Full pass complete — evaluate productivity and possibly expand window
            if self._disk_pass_resolved == 0 and self._disk_window < 6000:
                self._disk_window = min(self._disk_window * 3, 6000)
                logger.info(
                    "dreamer.disk_scan | pass complete, 0 resolutions — "
                    "expanding window to %d",
                    self._disk_window,
                )
            self._disk_offset = 0
            self._disk_pass_resolved = 0
            return stats

        for anchor in anchors:
            stats["disk_anchors_checked"] += 1
            # Skip if already in RAM anchor_index — handled by Phase 1 dream()
            if self._ctx.anchor_index and self._ctx.anchor_index.get(anchor.anchor_id):
                continue
            if self._reassess_outcome(anchor):
                stats["disk_outcomes_updated"] += 1
                self._disk_pass_resolved += 1  # T4 fix: track per-pass
                anchor.updated_at = int(time.time())
                await self._ctx.persistence.save_anchor(anchor)
                logger.debug(
                    "dreamer.disk_scan | resolved anchor=%s outcome=%s",
                    anchor.anchor_id, anchor.flags.get("outcome"),
                )

        self._disk_offset += PAGE_SIZE
        return stats

    # ------------------------------------------------------------------
    # Outcome reassessment (stub — extended by Phase 5+)
    # ------------------------------------------------------------------

    def _reassess_outcome(self, anchor: "Anchor") -> bool:
        """Check if outcome can be resolved from current RAM context.

        Returns True if the anchor was modified.
        Conditions for resolving 'pending' → 'success' or 'failure':
        - A later session in RAM references the same session (continuation chain)
        - That later session has a 'result' anchor_type
        """
        if anchor.flags.get("outcome") != "pending":
            return False

        # Look for a descendant in RAM that resolved this session
        for other_sid, other_sb in self._ctx.ram_index.items():
            other_anchor = self._ctx.anchor_index.get(other_sid)
            if not other_anchor:
                continue
            if other_anchor.flags.get("continuation_of") != anchor.anchor_id:
                continue
            if other_anchor.anchor_type == "milestone":
                anchor.flags["outcome"] = "success"
                return True
            if other_anchor.flags.get("outcome") in ("failure", "abandoned"):
                anchor.flags["outcome"] = other_anchor.flags["outcome"]
                return True

        return False
