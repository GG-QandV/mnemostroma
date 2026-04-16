# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
import sqlite3
import time as _time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import SystemContext

logger = logging.getLogger("mnemostroma.backup")

class BackupWorker:
    """Implement periodic SQLite database dumps as defined in FLASH-PATCH-20260415-B.
    
    Triggered periodically based on daemon start time (not cron-schedule).
    Records results to db_snapshots table.
    """

    def __init__(self, ctx: "SystemContext"):
        self.ctx = ctx
        self._running = False
        self._task: asyncio.Task | None = None
        self.interval_sec = getattr(ctx.config.storage, "backup_interval_hours", 3) * 3600

    async def start(self) -> None:
        """Start the background backup loop.

        On startup, checks if there are unbackedup records older than the interval.
        If yes → backup immediately. Otherwise → wait for next interval.
        """
        if self._task is not None:
            return
        self._running = True

        # Check if immediate backup is needed (unbackedup records older than interval)
        should_backup_now = await self._check_unbackedup_records()

        async def _startup_aware_loop():
            if should_backup_now:
                try:
                    await self._do_backup()
                    logger.info("BackupWorker: immediate backup triggered (unbackedup records detected)")
                except Exception as e:
                    logger.error("BackupWorker: immediate backup failed: %s", e, exc_info=True)

            # Continue with normal periodic backups
            await self._loop()

        self._task = asyncio.create_task(_startup_aware_loop(), name="backup_worker")
        logger.info("BackupWorker started (interval=%.1fh)", self.interval_sec / 3600)

    async def _check_unbackedup_records(self) -> bool:
        """Check if there are records older than backup interval that were not backed up.

        Returns:
            True if immediate backup should be triggered, False otherwise.
        """
        try:
            # Get last backup timestamp from db_snapshots
            last_backup_row = await self.ctx.db.execute(
                "SELECT MAX(ts) FROM db_snapshots"
            )
            last_backup_ts = await last_backup_row.fetchone()
            last_backup_ts = last_backup_ts[0] if last_backup_ts and last_backup_ts[0] else 0

            # Get earliest session created_at
            earliest_session = await self.ctx.db.execute(
                "SELECT MIN(created_at) FROM sessions"
            )
            earliest_ts_row = await earliest_session.fetchone()
            earliest_ts = earliest_ts_row[0] if earliest_ts_row and earliest_ts_row[0] else int(_time.time())

            # Check if earliest unbackedup record is older than interval
            now = int(_time.time())
            oldest_unbackedup = min(earliest_ts, last_backup_ts)

            # If there's a gap between last backup and earliest record, and it's >= interval
            if earliest_ts > last_backup_ts and (now - earliest_ts) >= self.interval_sec:
                logger.info(
                    "BackupWorker: unbackedup records detected (oldest: %d, age: %.1fh)",
                    earliest_ts,
                    (now - earliest_ts) / 3600,
                )
                return True

            return False
        except Exception as e:
            logger.debug("BackupWorker: check_unbackedup_records failed: %s", e)
            return False

    async def stop(self) -> None:
        """Stop the background backup loop."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("BackupWorker stopped")

    async def _loop(self) -> None:
        while self._running:
            # Shift the first backup to 'interval' after start
            await asyncio.sleep(self.interval_sec)
            try:
                await self._do_backup()
            except Exception as e:
                logger.error("BackupWorker: backup failed: %s", e, exc_info=True)

    async def _do_backup(self) -> None:
        """Perform actual DB backup and record metrics."""
        # 1. Flush pending writes
        if hasattr(self.ctx, "persistence"):
            await self.ctx.persistence.flush()

        backup_dir = Path.home() / ".mnemostroma" / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        # 2. Cleanup warning for old files
        now = _time.time()
        for f in backup_dir.glob("mnemo_*.db"):
            if now - f.stat().st_mtime > 30 * 86400:
                logger.warning("BackupWorker: old backup found (>30d): %s", f.name)

        # 3. Perform backup
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        dest = backup_dir / f"mnemo_{ts}.db"
        
        # Get source path from config or session
        db_path = getattr(self.ctx, "db_path", None)
        if not db_path:
            # Fallback to default if not wired explicitly in ctx
            db_path = Path.home() / ".mnemostroma" / "mnemostroma.db"
        else:
            db_path = Path(db_path)

        def _sync_backup():
            with sqlite3.connect(db_path) as src, sqlite3.connect(dest) as dst:
                src.backup(dst)

        await asyncio.to_thread(_sync_backup)
        
        # 4. Record to db_snapshots
        db_size_mb = dest.stat().st_size / (1024 * 1024)
        logs_size_mb = 0.0
        
        logs_path = getattr(self.ctx.config.logging, "db_path", "logs.db")
        # Handle relative/absolute logs path
        lp = Path(logs_path)
        if not lp.is_absolute():
            lp = db_path.parent / lp
            
        if lp.exists():
            logs_size_mb = lp.stat().st_size / (1024 * 1024)

        try:
            # Use ctx.db (aiosqlite) to insert metrics
            await self.ctx.db.execute(
                "INSERT INTO db_snapshots (ts, db_size_mb, logs_size_mb) VALUES (?, ?, ?)",
                (int(_time.time()), round(db_size_mb, 2), round(logs_size_mb, 2))
            )
            await self.ctx.db.commit()
            logger.info("BackupWorker: backup complete → %s (%.2f MB)", dest.name, db_size_mb)
        except Exception as e:
            logger.error("BackupWorker: failed to record snapshot metrics: %s", e)
