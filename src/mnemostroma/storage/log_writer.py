# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import json
import time
import aiosqlite
import logging
from typing import Any, Optional

logger = logging.getLogger("mnemostroma.logging")

class LogWriter:
    """Async structured log writer to logs.db."""

    def __init__(self, db_path: str, queue_size: int = 1000):
        self.db_path = db_path
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self._db: Optional[aiosqlite.Connection] = None
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self):
        """Initialize DB and start flush worker."""
        self._db = await aiosqlite.connect(self.db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        
        await self._db.execute("""
        CREATE TABLE IF NOT EXISTS onnx_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ts          INTEGER NOT NULL,          -- unix timestamp milliseconds
            component   TEXT NOT NULL,             -- "observer.filter", "tuner.conflict"
            event       TEXT NOT NULL,             -- "classify", "extract", "encode"
            data        TEXT NOT NULL,             -- JSON
            latency_ms  REAL DEFAULT 0.0,          -- component execution time
            session_id  TEXT,                       -- session identifier (if any)
            level       TEXT DEFAULT 'INFO'         -- INFO / WARNING / ERROR
        );
        """)
        
        # Indices
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_logs_ts ON onnx_logs(ts);")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_logs_component ON onnx_logs(component);")
        await self._db.execute("CREATE INDEX IF NOT EXISTS idx_logs_session ON onnx_logs(session_id);")

        # GAP 3: dissolution_log — eviction telemetry (P1 DDL, logging_checklist.md)
        await self._db.execute("""
        CREATE TABLE IF NOT EXISTS dissolution_log (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ts            INTEGER NOT NULL,       -- unix ms
            session_id    TEXT,                   -- evicted session or NULL for batch
            evicted_count INTEGER NOT NULL DEFAULT 0,
            ram_after     INTEGER NOT NULL DEFAULT 0
        )
        """)
        await self._db.execute(
            "CREATE INDEX IF NOT EXISTS idx_dissolution_ts ON dissolution_log(ts)"
        )

        await self._db.commit()
        self._running = True
        self._task = asyncio.create_task(self._flush_loop())
        logger.info(f"LogWriter started at {self.db_path}")

    def log_nowait(
        self,
        component: str,
        event: str,
        data: dict,
        latency_ms: float = 0.0,
        session_id: Optional[str] = None,
        level: str = "INFO",
    ):
        """Put log entry into queue — sync, never blocks."""
        if not self._running:
            return
        entry = (
            int(time.time() * 1000),
            component,
            event,
            json.dumps(data, ensure_ascii=False),
            latency_ms,
            session_id,
            level,
        )
        try:
            self.queue.put_nowait(entry)
        except asyncio.QueueFull:
            pass  # Drop — system health over telemetry

    async def log(self, component, event, data, latency_ms=0.0, session_id=None, level="INFO"):
        """Backward-compat async wrapper — delegates to log_nowait."""
        self.log_nowait(component, event, data, latency_ms, session_id, level)

    async def _flush_loop(self):
        """Background worker to batch write logs."""
        while True:
            batch = []
            try:
                try:
                    entry = await asyncio.wait_for(self.queue.get(), timeout=2.0)
                    batch.append(entry)
                    while len(batch) < 100:
                        try:
                            batch.append(self.queue.get_nowait())
                        except asyncio.QueueEmpty:
                            break
                except asyncio.TimeoutError:
                    if not self._running:
                        break
                    continue

                if batch and self._db:
                    await self._db.executemany(
                        "INSERT INTO onnx_logs (ts, component, event, data, latency_ms, session_id, level) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?)",
                        batch
                    )
                    await self._db.commit()
                    for _ in range(len(batch)):
                        self.queue.task_done()

                # Check exit AFTER processing batch
                if not self._running and self.queue.empty():
                    break

            except asyncio.CancelledError:
                # Drain remaining before exit
                await self._drain_remaining()
                break
            except Exception as e:
                logger.error(f"LogWriter flush error: {e}")
                await asyncio.sleep(1)

    async def _drain_remaining(self):
        """Flush any remaining queue items before shutdown."""
        batch = []
        while not self.queue.empty():
            try:
                batch.append(self.queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if batch and self._db:
            try:
                await self._db.executemany(
                    "INSERT INTO onnx_logs (ts, component, event, data, latency_ms, session_id, level) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    batch
                )
                await self._db.commit()
                for _ in range(len(batch)):
                    self.queue.task_done()
            except Exception as e:
                logger.error(f"LogWriter drain error: {e}")

    async def snapshot_db_sizes(self, db_size_mb: float, logs_size_mb: float) -> None:
        """Write a db size snapshot. Called by ConsolidationWorker every hour."""
        if self._db is None:
            return
        ts = int(time.time())
        await self._db.execute(
            "INSERT INTO db_snapshots (ts, db_size_mb, logs_size_mb) VALUES (?, ?, ?)",
            (ts, db_size_mb, logs_size_mb),
        )
        await self._db.commit()

    async def stop(self):
        """Shutdown LogWriter gracefully."""
        if not self._running:
            return

        self._running = False
        logger.info("Stopping LogWriter...")

        # Let flush_loop exit naturally (it checks _running after timeout)
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("LogWriter: flush loop did not exit in time, cancelling.")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass

        # Close DB after flush_loop is fully done
        if self._db:
            try:
                await self._db.close()
            except Exception as e:
                logger.error(f"LogWriter db close error: {e}")
            self._db = None

        logger.info("LogWriter stopped.")

# Components always logged in "safe" mode (bootstrap, health, errors)
# GAP 1: tools.inject, experience.signal, dissolver.evict promoted to safe-mode
# so token telemetry and eviction events reach the DB regardless of log mode.
_SAFE_MODE_COMPONENTS = frozenset({
    "conductor.bootstrap",
    "conductor.health",
    "conductor.shutdown",
    "tools.inject",
    "experience.signal",
    "dissolver.evict",
})

    ctx: Any,
    component: str,
    event: str,
    data: dict,
    latency_ms: float = 0.0,
    session_id: Optional[str] = None,
    level: str = "INFO",
):
    """Global helper for fire-and-forget structured logging.

    Modes (config.logging.mode):
      "safe"  — only bootstrap/health/shutdown events + all ERROR level
      "debug" — all events (current behaviour, for alpha testers)
    """
    if not (hasattr(ctx, 'log_writer') and ctx.log_writer):
        return

    log_cfg = getattr(getattr(ctx, 'config', None), 'logging', None)
    if log_cfg is not None:
        if not log_cfg.enabled:
            return
        if log_cfg.mode == "safe":
            if component not in _SAFE_MODE_COMPONENTS and level != "ERROR":
                return

    ctx.log_writer.log_nowait(component, event, data, latency_ms, session_id, level)
