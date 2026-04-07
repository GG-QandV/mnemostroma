# SPDX-License-Identifier: FSL-1.1-MIT
import aiosqlite
import asyncio
import json
import logging
import time
from typing import Any, List, Optional
from pathlib import Path
from .schemas import ALL_SCHEMAS

_LOGS_ID_DB_ = ""  # internal diagnostics id

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


async def check_anchor_schema(db: aiosqlite.Connection) -> None:
    """Add t_rel column to anchors if missing (migration for existing databases).

    Safe to run on every startup — ALTER TABLE is a no-op when the column exists
    (SQLite raises OperationalError with 'duplicate column name', which we swallow).
    """
    try:
        await db.execute(
            "ALTER TABLE anchors ADD COLUMN "
            "t_rel TEXT NOT NULL DEFAULT '{\"after\":[],\"before\":[],\"caused_by\":[],\"during\":[]}'"
        )
        await db.commit()
        logger.info("check_anchor_schema: t_rel column added to anchors")
    except Exception:
        pass  # column already exists or table not yet created — both are fine


class DatabaseManager:
    """Manager for async persistence to SQLite.

    Uses an internal asyncio.Queue to batch writes and avoid blocking
    the main Observer pipeline. Implements the async flush worker pattern
    defined in architecture_overview.md § 7.

    Args:
        db: Active aiosqlite connection.
        config: Full system Config (not config.storage, full Config).
        ctx: SystemContext passed.
    """

    def __init__(self, db: aiosqlite.Connection, config: Any, ctx: Optional[Any] = None):
        self.db = db
        self.config = config.storage
        self.ctx = ctx  # SystemContext — wired after bootstrap
        self.queue: asyncio.Queue = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._running: bool = False

    async def start(self) -> None:
        """Start the async flush worker."""
        if self._worker_task is None:
            self._running = True
            self._worker_task = asyncio.create_task(self._worker())
            logger.info("DatabaseManager worker started")

    async def flush(self) -> None:
        """Drain the pending write queue to SQLite immediately.

        Safe to call while _worker is running. Consumes all queued items
        synchronously via get_nowait(), bypassing the worker's batch timer.
        Stops at the stop sentinel (None) and returns it to the queue intact.
        Called by Dissolver before eviction and by the SIGUSR1 handler.
        """
        batch: List[Any] = []
        while not self.queue.empty():
            try:
                item = self.queue.get_nowait()
                self.queue.task_done()
                if item is None:          # stop sentinel — return it so stop() works
                    await self.queue.put(None)
                    break
                batch.append(item)
            except asyncio.QueueEmpty:
                break
        if batch:
            await self._flush_batch(batch)

    async def stop(self) -> None:
        """Gracefully stop the worker and flush remaining data."""
        self._running = False
        if self._worker_task:
            await self.queue.put(None)  # Sentinel
            await self._worker_task
            self._worker_task = None
            logger.info("DatabaseManager worker stopped")

    def queue_write(self, session: Any) -> None:
        """Add a SessionBrief to the persistence queue — sync, never blocks.

        On QueueFull: logs ERROR (not warning — this is an invariant violation:
        session is in RAM but will not reach disk) and increments
        ctx.metrics["dropped_sessions"] for monitoring.
        """
        try:
            self.queue.put_nowait(session)
        except asyncio.QueueFull:
            sid = getattr(session, 'session_id', '?')
            logger.error(
                "StorePipe queue full — session NOT persisted (RAM⊆DISK violated): %s", sid
            )
            if self.ctx:
                self.ctx.metrics["dropped_sessions"] = (
                    self.ctx.metrics.get("dropped_sessions", 0) + 1
                )

    async def check_embedding_dim(self, expected_dim: int) -> None:
        """Wipe stale embeddings if stored dimension != expected (768 -> 384 migration)."""
        try:
            async with self.db.execute("SELECT embedding FROM sessions WHERE embedding IS NOT NULL LIMIT 1") as cursor:
                row = await cursor.fetchone()
                if row is None or row[0] is None:
                    return # Empty DB or no embeddings
                
                stored_blob = row[0]
                # float16 = 2 bytes per dimension
                stored_dim = len(stored_blob) // 2
                
                if stored_dim == expected_dim:
                    return # Dimensions match
                
                logger.warning(
                    f"dim_migration | stored_dim={stored_dim} expected_dim={expected_dim} -> wiping stale data"
                )
                
                # Wipe all tables containing embeddings
                await self.db.execute("DELETE FROM sessions")
                # Wipe content tables if they exist
                await self.db.execute("DELETE FROM content_blocks")
                await self.db.execute("DELETE FROM content_versions")
                
                await self.db.commit()
                logger.warning("dim_migration | wipe complete, indices will rebuild empty")
                
        except aiosqlite.Error as e:
            logger.error(f"dim_migration check failed (SQLite): {e}")
        except Exception as e:
            logger.error(f"dim_migration check failed: {e}")

    async def get_all_embeddings(self, expected_dim: int = 768) -> List[tuple[str, Any]]:
        """Retrieve all session embeddings from SQLite for HNSW hydration.
        
        Args:
            expected_dim: Expected dimension of the embedding vector.
            
        Returns:
            List of (session_id, numpy_vector) tuples.
        """
        results = []
        try:
            import numpy as np
            async with self.db.execute(
                "SELECT session_id, embedding FROM sessions WHERE embedding IS NOT NULL"
            ) as cursor:
                async for row in cursor:
                    session_id, raw_bytes = row
                    try:
                        vec = np.frombuffer(raw_bytes, dtype=np.float16)
                        if vec.shape[0] != expected_dim:
                            logger.warning(f"Dimension mismatch for {session_id}: expected {expected_dim}, got {vec.shape[0]}")
                            continue
                        results.append((session_id, vec))
                    except Exception as e:
                        logger.error(f"Failed to deserialize embedding for {session_id}: {e}")
        except Exception as e:
            logger.error(f"Error fetching embeddings for hydration: {e}")
        
        return results

    async def get_all_session_briefs(self) -> List[Any]:
        """Retrieve all session metadata for ram_index hydration.
        
        Returns:
            List of SessionBrief objects.
        """
        from ..memory.session_index import SessionBrief
        results = []
        try:
            import numpy as np
            async with self.db.execute(
                """SELECT session_id, created_at, importance, tags, brief, 
                          conflict, urgency, deadline_ts, urgency_expired, bare_entity, 
                          implicit_score, resolution, embedding FROM sessions"""
            ) as cursor:
                async for row in cursor:
                    session_id, created_at, importance, tags_json, brief, conflict, \
                    urgency, deadline_ts, urgency_expired, bare_entity, \
                    implicit_score, resolution, embed_bytes = row
                    
                    embedding = None
                    if embed_bytes:
                        embedding = np.frombuffer(embed_bytes, dtype=np.float16)
                    
                    sb = SessionBrief(
                        session_id=session_id,
                        brief=brief,
                        tags=json.loads(tags_json),
                        importance=importance,
                        score=0.0, # Dynamic
                        resolution=resolution,
                        created_at=created_at,
                        conflict_flag=bool(conflict),
                        urgency=urgency,
                        deadline_ts=deadline_ts,
                        urgency_expired=bool(urgency_expired),
                        bare_entity=bool(bare_entity),
                        embedding=embedding,
                        implicit_score=implicit_score,
                        embedding_model_version="gte-multilingual-base-int8-v1"
                    )
                    results.append(sb)
        except Exception as e:
            logger.error(f"Error fetching session briefs for hydration: {e}")
            
        return results

    async def get_session_by_id(self, session_id: str) -> Optional[Any]:
        """Load a single session from SQLite by session_id (cold load for ctx.load()).

        Returns SessionBrief or None if not found.
        """
        from ..memory.session_index import SessionBrief
        try:
            import numpy as np
            async with self.db.execute(
                """SELECT session_id, created_at, importance, tags, brief,
                          conflict, urgency, deadline_ts, urgency_expired, bare_entity,
                          implicit_score, resolution, embedding
                   FROM sessions WHERE session_id = ?""",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                session_id_, created_at, importance, tags_json, brief, conflict, \
                urgency, deadline_ts, urgency_expired, bare_entity, \
                implicit_score, resolution, embed_bytes = row

                embedding = None
                if embed_bytes:
                    embedding = np.frombuffer(embed_bytes, dtype=np.float16)

                return SessionBrief(
                    session_id=session_id_,
                    brief=brief,
                    tags=json.loads(tags_json),
                    importance=importance,
                    score=0.0,
                    resolution=resolution,
                    created_at=created_at,
                    conflict_flag=bool(conflict),
                    urgency=urgency,
                    deadline_ts=deadline_ts,
                    urgency_expired=bool(urgency_expired),
                    bare_entity=bool(bare_entity),
                    embedding=embedding,
                    implicit_score=implicit_score,
                    embedding_model_version="multilingual-e5-small",
                )
        except Exception as e:
            logger.error(f"get_session_by_id({session_id}): {e}")
            return None

    async def get_all_content_embeddings(self, expected_dim: int = 768) -> list[tuple[str, int, Any]]:
        """Retrieve all content embeddings for HNSW content hydration.

        WHY: Necessary for cold bootstrap which restores the content layer focus.
        Returns:
            List of (content_id, version, numpy_vector) tuples.
        """
        results = []
        try:
            import numpy as np
            async with self.db.execute(
                "SELECT content_id, version, embedding FROM content_versions WHERE embedding IS NOT NULL"
            ) as cursor:
                async for row in cursor:
                    content_id, version, raw_bytes = row
                    try:
                        vec = np.frombuffer(raw_bytes, dtype=np.float16)
                        if vec.shape[0] != expected_dim:
                            logger.warning(f"Content dim mismatch {content_id}_v{version}: expected {expected_dim}, got {vec.shape[0]}")
                            continue
                        results.append((content_id, version, vec))
                    except Exception as e:
                        logger.error(f"Failed to deserialize content embedding {content_id}_v{version}: {e}")
        except Exception as e:
            logger.error(f"Error fetching content embeddings: {e}")
        return results

    async def save_anchor(self, anchor: Any) -> None:
        """Persist anchor to SQLite."""
        data = anchor.to_dict()
        try:
            await self.db.execute(
                """INSERT OR REPLACE INTO anchors
                   (anchor_id, session_id, anchor_type, brief, key_facts, flags,
                    decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    data["anchor_id"],
                    data["session_id"],
                    data["anchor_type"],
                    data["brief"],
                    json.dumps(data["key_facts"], ensure_ascii=False),
                    json.dumps(data["flags"], ensure_ascii=False),
                    data["decay_level"],
                    data["access_count"],
                    data["last_accessed_at"],
                    json.dumps(data.get("t_rel", {"after": [], "before": [], "caused_by": [], "during": []}), ensure_ascii=False),
                    data["created_at"],
                    data["updated_at"],
                )
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to save anchor {anchor.anchor_id}: {e}")

    async def load_anchors(self, limit: int = 1000) -> list:
        """Load most recently accessed anchors for RAM index hydration."""
        anchors = []
        try:
            async with self.db.execute(
                """SELECT anchor_id, session_id, anchor_type, brief, key_facts, flags,
                          decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at
                   FROM anchors
                   ORDER BY last_accessed_at DESC
                   LIMIT ?""",
                (limit,)
            ) as cursor:
                async for row in cursor:
                    from ..subconscious.anchor import Anchor
                    anchors.append(Anchor(
                        anchor_id=row[0],
                        session_id=row[1],
                        anchor_type=row[2],
                        brief=row[3],
                        key_facts=json.loads(row[4]),
                        flags=json.loads(row[5]),
                        decay_level=row[6],
                        access_count=row[7],
                        last_accessed_at=row[8],
                        t_rel=json.loads(row[9]),
                        created_at=row[10],
                        updated_at=row[11],
                    ))
        except Exception as e:
            logger.error(f"Error loading anchors: {e}")
        return anchors

    async def get_anchor(self, anchor_id: str) -> Optional[Any]:
        """Load single anchor from SQLite (for resurface from silt)."""
        try:
            async with self.db.execute(
                """SELECT anchor_id, session_id, anchor_type, brief, key_facts, flags,
                          decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at
                   FROM anchors WHERE anchor_id = ?""",
                (anchor_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None

                from ..subconscious.anchor import Anchor
                return Anchor(
                    anchor_id=row[0],
                    session_id=row[1],
                    anchor_type=row[2],
                    brief=row[3],
                    key_facts=json.loads(row[4]),
                    flags=json.loads(row[5]),
                    decay_level=row[6],
                    access_count=row[7],
                    last_accessed_at=row[8],
                    t_rel=json.loads(row[9]),
                    created_at=row[10],
                    updated_at=row[11],
                )
        except Exception as e:
            logger.error(f"Error getting anchor {anchor_id}: {e}")
            return None


    async def check_experience_schema(self) -> None:
        """Add emotion columns to experience_metrics if they don't exist (v1.4 migration)."""
        new_columns = [
            ("emotion_positive",      "INTEGER NOT NULL DEFAULT 0"),
            ("emotion_negative",      "INTEGER NOT NULL DEFAULT 0"),
            ("emotion_intensity_sum", "REAL    NOT NULL DEFAULT 0.0"),
        ]
        try:
            async with self.db.execute("PRAGMA table_info(experience_metrics)") as cursor:
                existing = {row[1] async for row in cursor}
            for col_name, col_def in new_columns:
                if col_name not in existing:
                    await self.db.execute(
                        f"ALTER TABLE experience_metrics ADD COLUMN {col_name} {col_def}"
                    )
                    logger.info(f"experience_schema: added column {col_name}")
            await self.db.commit()
        except Exception as e:
            logger.error(f"check_experience_schema failed: {e}")

    async def upsert_experience(self, tag: str, session_count: int, score_sum: float,
                                conflict_count: int, last_updated: int,
                                emotion_positive: int = 0, emotion_negative: int = 0,
                                emotion_intensity_sum: float = 0.0) -> None:
        """Upsert a single experience cluster row."""
        try:
            await self.db.execute(
                """INSERT INTO experience_metrics
                       (tag, session_count, score_sum, conflict_count, last_updated,
                        emotion_positive, emotion_negative, emotion_intensity_sum)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(tag) DO UPDATE SET
                       session_count=excluded.session_count,
                       score_sum=excluded.score_sum,
                       conflict_count=excluded.conflict_count,
                       last_updated=excluded.last_updated,
                       emotion_positive=excluded.emotion_positive,
                       emotion_negative=excluded.emotion_negative,
                       emotion_intensity_sum=excluded.emotion_intensity_sum""",
                (tag, session_count, round(score_sum, 4), conflict_count, last_updated,
                 emotion_positive, emotion_negative, round(emotion_intensity_sum, 4))
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to upsert experience for tag '{tag}': {e}")

    async def load_experience(self) -> List[dict]:
        """Load all experience clusters for RAM hydration on bootstrap."""
        rows = []
        try:
            async with self.db.execute(
                """SELECT tag, session_count, score_sum, conflict_count, last_updated,
                          emotion_positive, emotion_negative, emotion_intensity_sum
                   FROM experience_metrics"""
            ) as cursor:
                async for row in cursor:
                    rows.append({
                        "tag": row[0],
                        "session_count": row[1],
                        "score_sum": row[2],
                        "conflict_count": row[3],
                        "last_updated": row[4],
                        "emotion_positive": row[5] if row[5] is not None else 0,
                        "emotion_negative": row[6] if row[6] is not None else 0,
                        "emotion_intensity_sum": row[7] if row[7] is not None else 0.0,
                    })
        except Exception as e:
            logger.error(f"Failed to load experience metrics: {e}")
        return rows

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
