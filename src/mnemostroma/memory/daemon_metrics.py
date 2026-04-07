# SPDX-License-Identifier: FSL-1.1-MIT
"""Daemon-side metrics writers — pulse.json and status.json.

PulseWriter  — lightweight heartbeat every 5s  → ~/.mnemostroma/pulse.json
StatusWriter — full metrics snapshot every 30s → ~/.mnemostroma/status.json

Both are asyncio tasks started by Conductor. External tools (watch, tray,
monitoring scripts) read these files. No MCP, no IPC, no extra dependencies.
"""
import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.daemon_metrics")

METRICS_DIR = Path.home() / ".mnemostroma"
PULSE_PATH  = METRICS_DIR / "pulse.json"
STATUS_PATH = METRICS_DIR / "status.json"


class PulseWriter:
    """Write minimal heartbeat to pulse.json every interval seconds.

    Output: {"sessions": N, "ram_mb": X, "ram_pct": X, "urgency_active": N, "ts": epoch}
    """

    def __init__(self, ctx: "SystemContext", interval: float = 5.0):
        self.ctx = ctx
        self.interval = interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="pulse_writer")
        logger.info("PulseWriter started (interval=%.0fs → %s)", self.interval, PULSE_PATH)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                self._write()
            except Exception as e:
                logger.warning("PulseWriter write failed: %s", e)
            await asyncio.sleep(self.interval)

    def _write(self) -> None:
        ram_mb = 0.0
        try:
            import psutil
            ram_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except Exception:
            pass

        try:
            budget_mb = float(self.ctx.config.resources.ram_budget_mb)
        except Exception:
            budget_mb = 631.0
        ram_pct = round(ram_mb / budget_mb * 100, 1) if budget_mb > 0 else 0.0

        urgency_active = 0
        if hasattr(self.ctx, "urgency_index"):
            urgency_active = sum(
                1 for v in self.ctx.urgency_index.values()
                if not v.get("expired", False)
            )

        payload = {
            "sessions": len(self.ctx.ram_index),
            "ram_mb": ram_mb,
            "ram_pct": ram_pct,
            "urgency_active": urgency_active,
            "ts": int(time.time()),
        }
        PULSE_PATH.write_text(json.dumps(payload), encoding="utf-8")


class StatusWriter:
    """Write extended system metrics to status.json every interval seconds.

    Output: {"ts", "ram_mb", "ram_index_count", "session_index_count",
             "content_index_count", "pending_writes", "metrics"}
    """

    def __init__(self, ctx: "SystemContext", interval: float = 30.0):
        self.ctx = ctx
        self.interval = interval
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="status_writer")
        logger.info("StatusWriter started (interval=%.0fs → %s)", self.interval, STATUS_PATH)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            try:
                self._write()
            except Exception as e:
                logger.warning("StatusWriter write failed: %s", e)
            await asyncio.sleep(self.interval)

    def _write(self) -> None:
        ram_mb = 0.0
        try:
            import psutil
            ram_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 2)
        except Exception:
            pass

        persistence = getattr(self.ctx, "persistence", None)
        pending = persistence.pending_writes() if persistence else 0

        payload = {
            "ts": int(time.time()),
            "ram_mb": ram_mb,
            "ram_index_count": len(self.ctx.ram_index),
            "session_index_count": (
                self.ctx.session_index.get_current_count()
                if self.ctx.session_index else 0
            ),
            "content_index_count": (
                self.ctx.content_index.get_current_count()
                if self.ctx.content_index else 0
            ),
            "pending_writes": pending,
            "metrics": getattr(self.ctx, "metrics", {}),
        }
        STATUS_PATH.write_text(json.dumps(payload, default=str), encoding="utf-8")
