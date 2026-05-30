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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..core import SystemContext
    from ..subconscious.anchor import Anchor

logger = logging.getLogger("mnemostroma.dreamer")


class Dreamer:
    """Idle-triggered anchor reassessment worker.

    Lifecycle: started by Conductor after bootstrap, runs a background loop
    polling `conductor.is_idle()`. When idle, runs one reassessment cycle.
    """

    def __init__(self, conductor: object, ctx: SystemContext):
        self._conductor = conductor
        self._ctx = ctx
        self._running = False
        self._task: asyncio.Task | None = None
        # Phase 2 — disk scan state (RAM-only, resets to 0 on daemon restart — intentional)
        self._disk_offset: int = 0
        self._disk_window: int = 1000
        self._disk_pass_resolved: int = 0  # T4 fix: counts resolutions per full pass
        self.auto_bridge: AutoBridgeWorker | None = AutoBridgeWorker(conductor, ctx)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())
        if self.auto_bridge:
            await self.auto_bridge.start()
        logger.info("Dreamer started.")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self.auto_bridge:
            await self.auto_bridge.stop()
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


        logger.info(
            "Dreamer cycle: checked=%d outcomes_updated=%d resurfaced=%d",
            stats["anchors_checked"], stats["outcomes_updated"], stats["resurfaced"],
        )

        if self.auto_bridge and self._conductor.is_idle():
            asyncio.create_task(self.auto_bridge._try_bridge())

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

    def _reassess_outcome(self, anchor: Anchor) -> bool:
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

# ---------------------------------------------------------------------------
# AutoBridgeWorker
# ---------------------------------------------------------------------------

class AutoBridgeWorker:
    """Idle-triggered automatic context bridge generator.

    Fires when Dreamer detects idle state AND a session exists in RAM.
    Generates a bridge summary and persists it via log_event().
    Protects against: duplicates (cooldown), LLM failure (fallback),
    race conditions (asyncio.shield), empty sessions (guard).
    """

    def __init__(self, conductor: object, ctx: SystemContext) -> None:
        self._conductor = conductor
        self._ctx = ctx
        self._cooldown_sec: int = 1800       # from config: session_closure.cooldown_sec
        self._last_bridge: dict[str, float] = {}   # session_id -> timestamp, RAM-only
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        poll_sec = 120
        while self._running:
            try:
                await asyncio.sleep(poll_sec)
                if getattr(self._conductor, "is_idle", lambda: False)():
                    await self._try_bridge()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("AutoBridgeWorker._run error: %s", e, exc_info=True)

    async def _try_bridge(self) -> None:
        """Attempt to generate bridge for current session if cooldown passed."""
        # 1. Get current session_id from ctx._current_session_file or ram_index latest
        session_id = self._get_active_session_id()
        if not session_id:
            return

        # 2. Cooldown guard — skip if bridge generated recently for this session
        now = time.time()
        if now - self._last_bridge.get(session_id, 0) < self._cooldown_sec:
            return

        # 3. Get session brief from ram_index
        sb = self._ctx.ram_index.get(session_id)
        if not sb:
            return

        # 4. Collect anchor facts for this session
        anchors = self._collect_session_anchors(session_id)

        # 5. Generate bridge text (with fallback)
        bridge_text = await self._generate_bridge(sb, anchors)

        # 6. Compute coverage score
        coverage = self._compute_coverage(bridge_text, anchors)

        # 7. Persist via log_event — asyncio.shield protects from cancellation
        quality = "LOW" if coverage < 0.5 else "OK"
        await asyncio.shield(
        )

        # 8. Update cooldown
        self._last_bridge[session_id] = now

        logger.info(
            "AutoBridge | session=%s coverage=%.2f quality=%s anchors=%d",
            session_id, coverage, quality, len(anchors),
        )

    def _get_active_session_id(self) -> str | None:
        """Read from ~/.mnemostroma/current_session file (written by Observer)."""
        from pathlib import Path
        p = Path.home() / ".mnemostroma" / "current_session"
        try:
            sid = p.read_text(encoding="utf-8").strip()
            return sid if sid else None
        except Exception:
            return None

    def _collect_session_anchors(self, session_id: str) -> list[str]:
        """Return text representations of anchors linked to session_id."""
        if not self._ctx.anchor_index:
            return []
        result = []
        for anchor in self._ctx.anchor_index.all():
            if getattr(anchor, "session_id", None) == session_id:
                result.append(f"[{anchor.anchor_type}] {anchor.text}")
        return result[:20]  # cap at 20 to avoid token overflow

    async def _generate_bridge(self, sb: Any, anchors: list[str]) -> str:
        """Generate bridge summary. Fallback to anchor list if generation fails."""
        try:
            # Use existing ctx_semantic summary pattern — no new LLM dependency
            brief = getattr(sb, "brief", "") or ""
            tags = ", ".join(getattr(sb, "tags", []) or [])
            anchor_block = "\n".join(anchors) if anchors else "No anchors."
            return (
                f"Session summary: {brief}\n"
                f"Tags: {tags}\n"
                f"Key anchors:\n{anchor_block}"
            )
        except Exception as e:
            logger.warning("AutoBridge: generation failed, using fallback: %s", e)
            return "\n".join(anchors) if anchors else "Bridge generation failed."

    def _compute_coverage(self, bridge_text: str, anchors: list[str]) -> float:
        """Fraction of anchor texts that appear in bridge (substring match)."""
        if not anchors:
            return 1.0   # vacuously complete
        hits = sum(1 for a in anchors if a[:30] in bridge_text)
        return hits / len(anchors)

