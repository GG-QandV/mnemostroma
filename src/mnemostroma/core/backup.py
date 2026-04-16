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
        """Start the background backup loop."""
        if self._task is not None:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(), name="backup_worker")
        logger.info("BackupWorker started (interval=%.1fh)", self.interval_sec / 3600)

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
