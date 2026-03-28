# SPDX-License-Identifier: FSL-1.1-MIT
import aiosqlite
import asyncio
import json
import logging
import time
from typing import Any, List, Optional
from pathlib import Path
from .schemas import ALL_SCHEMAS

logger = logging.getLogger("mnemostroma.storage")

async def init_db(db_path: str | Path, config: Optional[Any] = None) -> aiosqlite.Connection:
    """Initialize SQLite database with WAL mode and schemas.

    Applies WAL journal mode, cache and mmap sizes from config if provided,
    and executes all table schemas.
    """
    db = await aiosqlite.connect(db_path)

    # Use config values or defaults (v1.5.1 fix)
    cache_sz = -8000 # 8MB default
    mmap_sz = 134217728 # 128MB default
    
    if config and hasattr(config, 'resources'):
        cache_sz = -int(config.resources.sqlite_cache_mb * 1024)
        mmap_sz = int(config.resources.sqlite_mmap_mb * 1024 * 1024)

    # Required PRAGMAs per spec (architecture_overview.md § 7)
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute(f"PRAGMA cache_size={cache_sz}")
    await db.execute(f"PRAGMA mmap_size={mmap_sz}")

    # Apply all table schemas and indices
    for schema in ALL_SCHEMAS:
        await db.execute(schema)

    await db.commit()
    logger.info(f"Database initialized at {db_path}")
    return db

class DatabaseManager:
    """Manager for async persistence to SQLite.

    Uses an internal asyncio.Queue to batch writes and avoid blocking
    the main Observer pipeline. Implements the async flush worker pattern
    defined in architecture_overview.md § 7.

    Args:
        db: Active aiosqlite connection.
        config: Full system Config (not config.storage, full Config).
    def __init__(self, db: aiosqlite.Connection, config: Any):
        self.db = db
        self.config = config.storage
        self.queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> None:
        """Start the async flush worker."""
        if self._worker_task is None:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("DatabaseManager worker started")

    async def stop(self) -> None:
        """Gracefully stop the worker and flush remaining data."""
        self._running = False
        if self._worker_task:
            await self.queue.put(None)  # Sentinel
            await self._worker_task
            self._worker_task = None
            logger.info("DatabaseManager worker stopped")

    async def queue_write(self, session: Any) -> None:
        """Add a SessionBrief to the persistence queue.

        Args:
            session: SessionBrief instance to persist.
        """
        await self.queue.put(session)

    async def _worker(self) -> None:
        """Background worker that flushes batched sessions to SQLite."""
        batch: List[Any] = []
        last_flush = time.time()

        while True:
            try:
                try:
                    # Wait for items OR timeout to trigger periodic flush
                    item = await asyncio.wait_for(
                        self.queue.get(),
                        timeout=self.config.async_flush_interval_sec
                    )
                except asyncio.TimeoutError:
                    item = "TIMEOUT"

                if item is None:  # Shutdown sentinel MUST be checked first
                    if batch:
                        await self._flush_batch(batch)
                    self.queue.task_done()
                    break

                if item != "TIMEOUT":
                    batch.append(item)
                    # We call task_done() after processing or batching
                    self.queue.task_done()

                now = time.time()
                should_flush = (
                    len(batch) >= self.config.batch_flush_size or
                    (now - last_flush) >= self.config.async_flush_interval_sec
                )
                if batch and should_flush:
                    await self._flush_batch(batch)
                    batch = []
                    last_flush = now

            except aiosqlite.Error as e:
                logger.error(f"SQLite error in worker: {e}", exc_info=True)
            except Exception as e:
                logger.error(f"Error in DatabaseManager worker: {e}", exc_info=True)

    async def _flush_batch(self, batch: List[Any]) -> None:
        """Persist a batch of objects to SQLite.
        
        Handles SessionBrief (session index) and dict (content branch) payloads.
        """
        now_ts = int(time.time())

        for item in batch:
            try:
                # 1. Handle SessionBrief (Session Index)
                if hasattr(item, 'session_id') and hasattr(item, 'brief'):
                    session = item
                    urgency_active = (
                        bool(getattr(session, 'deadline_ts', None)) and
                        not session.urgency_expired and
                        (session.deadline_ts or 0) > now_ts
                    )

                    await self.db.execute(
                        """
                        INSERT OR REPLACE INTO sessions
                        (session_id, created_at, updated_at, importance, tags, brief,
                         conflict, urgency, deadline_ts, urgency_active, urgency_expired,
                         bare_entity, embedding_model_version, embedding, 
                         use_count, deep_use_count, last_use_ts, implicit_score)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session.session_id,
                            session.created_at,
                            now_ts,
                            session.importance,
                            json.dumps(session.tags),
                            session.brief,
                            1 if session.conflict_flag else 0,
                            session.urgency,
                            session.deadline_ts,
                            1 if urgency_active else 0,
                            1 if session.urgency_expired else 0,
                            1 if session.bare_entity else 0,
                            session.embedding_model_version,
                            session.embedding.tobytes() if session.embedding is not None else None,
                            getattr(session, 'use_count', 0),
                            getattr(session, 'deep_use_count', 0),
                            getattr(session, 'last_use_ts', None),
                            getattr(session, 'implicit_score', 0.5),
                        )
                    )

                    # Persist precision_items to precision_log if present
                    precision_items = getattr(session, 'precision_items', [])
                    if precision_items:
                        for p in precision_items:
                            await self.db.execute(
                                """
                                INSERT OR IGNORE INTO precision_log
                                (precision_id, session_id, type, value, context_tag, importance, created_at)
                                VALUES (?, ?, ?, ?, ?, ?, ?)
                                """,
                                (
                                    p.get("id", f"{session.session_id}_{p.get('type', 'item')}"),
                                    session.session_id,
                                    p.get("type"),
                                    p.get("value"),
                                    p.get("context_tag"),
                                    session.importance,
                                    session.created_at,
                                )
                            )

                # 2. Handle ContentBlock (Content Branch)
                elif isinstance(item, dict) and item.get("type") == "content_block":
                    await self.db.execute(
                        "INSERT OR REPLACE INTO content_blocks (content_id, session_id, content_type, status) VALUES (?, ?, ?, ?)",
                        (item["content_id"], item["session_id"], item["content_type"], item["status"])
                    )

                # 3. Handle ContentVersion (Content Branch)
                elif isinstance(item, dict) and item.get("type") == "content_version":
                    await self.db.execute(
                        """
                        INSERT INTO content_versions 
                        (content_id, version, content_hash, content_raw, content_diff, content_tags, why_changed, embedding, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["content_id"],
                            item["version"],
                            item["content_hash"],
                            item["content_raw"],
                            item["content_diff"],
                            json.dumps(item["content_tags"]),
                            item["why_changed"],
                            item["embedding"],
                            item["created_at"]
                        )
                    )

            except aiosqlite.Error as e:
                logger.error(f"SQLite error flushing batch item: {e}", exc_info=True)

        await self.db.commit()

        logger.debug(f"Flushed {len(batch)} sessions to SQLite")
