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

    await db.execute("""
        CREATE TABLE IF NOT EXISTS db_snapshots (
            ts        INTEGER NOT NULL,
            db_size_mb  REAL NOT NULL DEFAULT 0.0,
            logs_size_mb REAL NOT NULL DEFAULT 0.0
        )
    """)
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_snapshots_ts ON db_snapshots(ts)"
    )

    # Migrations
    await check_anchor_schema(db)
    await check_session_schema(db)

    await db.commit()
    logger.info(f"Database initialized at {db_path}")
    return db


async def check_anchor_schema(db: aiosqlite.Connection) -> None:
    """Add missing columns to anchors table (migrations)."""
    # t_rel — added in v1.6
    try:
        await db.execute(
            "ALTER TABLE anchors ADD COLUMN "
            "t_rel TEXT NOT NULL DEFAULT '{\"after\":[],\"before\":[],\"caused_by\":[],\"during\":[]}'"
        )
        await db.commit()
    except Exception:
        pass
    # embedding — added in Phase 11 (Guardian/Surfacing semantic match)
    try:
        await db.execute("ALTER TABLE anchors ADD COLUMN embedding BLOB")
        await db.commit()
    except Exception:
        pass
    # idx_anchors_flags_outcome — added in Phase 2 (Dreamer disk scan)
    # Expression indices require SQLite 3.9.0+. Silently skip on older builds.
    try:
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_anchors_flags_outcome "
            "ON anchors(json_extract(flags, '$.outcome'))"
        )
        await db.commit()
    except Exception:
        pass

async def check_session_schema(db: aiosqlite.Connection) -> None:
    """Migrate sessions table for v1.7.1 (resolution, intensity)."""
    # 1. resolution
    try:
        await db.execute("ALTER TABLE sessions ADD COLUMN resolution REAL DEFAULT 1.0")
        await db.commit()
    except Exception:
        pass
    
    # 2. intensity
    try:
        await db.execute("ALTER TABLE sessions ADD COLUMN intensity REAL DEFAULT 0.0")
        await db.commit()
    except Exception:
        pass

    # 3. session_type (v1.11.0)
    try:
        await db.execute("ALTER TABLE sessions ADD COLUMN session_type TEXT")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_sessions_type ON sessions(session_type)")
        await db.commit()
    except Exception:
        pass


class DatabaseManager:
    """Manager for async persistence to SQLite.

    Uses an internal asyncio.Queue to batch writes and avoid blocking
    the main Observer pipeline. Implements the async flush worker pattern
    defined in architecture_overview.md § 7.

    Args:
        db: Active aiosqlite connection.
        config: Full system Config (not config.storage, full Config).
        ctx: SystemContext passed for log_event instrumentation.
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
                          implicit_score, resolution, intensity, embedding FROM sessions"""
            ) as cursor:
                async for row in cursor:
                    session_id, created_at, importance, tags_json, brief, conflict, \
                    urgency, deadline_ts, urgency_expired, bare_entity, \
                    implicit_score, resolution, intensity, embed_bytes = row
                    
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
                        intensity=intensity,
                        embedding_model_version="multilingual-e5-small"
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
                          implicit_score, resolution, intensity, embedding
                   FROM sessions WHERE session_id = ?""",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                session_id_, created_at, importance, tags_json, brief, conflict, \
                urgency, deadline_ts, urgency_expired, bare_entity, \
                implicit_score, resolution, intensity, embed_bytes = row

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
                    intensity=intensity,
                    embedding_model_version="multilingual-e5-small",
                )
        except Exception as e:
            logger.error(f"get_session_by_id({session_id}): {e}")
            return None

    # Alias for SessionPort compatibility
    load_session = get_session_by_id

    async def delete_session(self, session_id: str) -> None:
        """Permanently delete a session and its associated content/precision logs."""
        try:
            await self.db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
            await self.db.execute("DELETE FROM content_blocks WHERE session_id = ?", (session_id,))
            await self.db.execute("DELETE FROM precision_log WHERE session_id = ?", (session_id,))
            await self.db.commit()
            logger.info(f"Session {session_id} deleted from SQLite")
        except Exception as e:
            logger.error(f"Failed to delete session {session_id}: {e}")
            raise

    async def update_session_score(self, session_id: str, score: float) -> None:
        """Update the implicit_score for a session."""
        try:
            await self.db.execute(
                "UPDATE sessions SET implicit_score = ?, updated_at = ? WHERE session_id = ?",
                (score, int(time.time()), session_id)
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to update score for session {session_id}: {e}")
            raise

    async def list_sessions_by_score(self, limit: int = 50) -> list:
        """List sessions ordered by implicit_score DESC."""
        from ..memory.session_index import SessionBrief
        import numpy as np
        results = []
        try:
            async with self.db.execute(
                """SELECT session_id, created_at, importance, tags, brief,
                          conflict, urgency, deadline_ts, urgency_expired, bare_entity,
                          implicit_score, resolution, intensity, embedding
                   FROM sessions
                   ORDER BY implicit_score DESC
                   LIMIT ?""",
                (limit,)
            ) as cursor:
                async for row in cursor:
                    embedding = None
                    if row[13] is not None:
                        try:
                            embedding = np.frombuffer(row[13], dtype=np.float16)
                        except Exception:
                            pass
                    results.append(SessionBrief(
                        session_id=row[0],
                        created_at=row[1],
                        importance=row[2],
                        tags=json.loads(row[3]),
                        brief=row[4],
                        score=row[10], # Use implicit_score
                        resolution=row[11] if row[11] is not None else 1.0,
                        conflict_flag=bool(row[5]),
                        urgency=row[6],
                        deadline_ts=row[7],
                        urgency_expired=bool(row[8]),
                        bare_entity=bool(row[9]),
                        embedding=embedding,
                        implicit_score=row[10] if row[10] is not None else 0.5,
                        intensity=row[12] if row[12] is not None else 0.0,
                        embedding_model_version="multilingual-e5-small",
                    ))
        except Exception as e:
            logger.error(f"list_sessions_by_score failed: {e}")
        return results

    async def list_sessions_by_tags(self, tags: list[str], limit: int = 50) -> list:
        """Unified wrapper for find_sessions_by_flags(has_tag=...)."""
        # For multi-tag support, we take the first one or implement a complex query.
        # Starting with simpler mapping as requested.
        return await self.find_sessions_by_flags(has_tag=tags[0] if tags else None, limit=limit)

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
        import numpy as np
        emb_bytes = None
        if anchor.embedding is not None:
            emb_bytes = anchor.embedding.astype(np.float16).tobytes()
        try:
            await self.db.execute(
                """INSERT OR REPLACE INTO anchors
                   (anchor_id, session_id, anchor_type, brief, key_facts, flags,
                    decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at,
                    embedding)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                    emb_bytes,
                )
            )
            await self.db.commit()
        except Exception as e:
            logger.error(f"Failed to save anchor {anchor.anchor_id}: {e}")

    async def load_anchors(self, limit: int = 1000) -> list:
        """Load most recently accessed anchors for RAM index hydration."""
        import numpy as np
        anchors = []
        try:
            async with self.db.execute(
                """SELECT anchor_id, session_id, anchor_type, brief, key_facts, flags,
                          decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at,
                          embedding
                   FROM anchors
                   ORDER BY last_accessed_at DESC
                   LIMIT ?""",
                (limit,)
            ) as cursor:
                async for row in cursor:
                    from ..subconscious.anchor import Anchor
                    emb = None
                    if row[12] is not None:
                        try:
                            emb = np.frombuffer(row[12], dtype=np.float16).astype(np.float32)
                        except Exception:
                            pass
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
                        embedding=emb,
                    ))
        except Exception as e:
            logger.error(f"Error loading anchors: {e}")
        return anchors

    async def get_anchor(self, anchor_id: str) -> Optional[Any]:
        """Load single anchor from SQLite (for resurface from silt)."""
        import numpy as np
        try:
            async with self.db.execute(
                """SELECT anchor_id, session_id, anchor_type, brief, key_facts, flags,
                          decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at,
                          embedding
                   FROM anchors WHERE anchor_id = ?""",
                (anchor_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None

                emb = None
                if row[12] is not None:
                    try:
                        emb = np.frombuffer(row[12], dtype=np.float16).astype(np.float32)
                    except Exception:
                        pass

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
                    embedding=emb,
                )
        except Exception as e:
            logger.error(f"Error getting anchor {anchor_id}: {e}")
            return None

    async def find_anchors_by_flags(
        self,
        outcome: Optional[str] = None,
        multi_session: Optional[bool] = None,
        anchor_type: Optional[str] = None,
        session_id: Optional[str] = None,
        decay_level_max: int = 3,
        limit: int = 50,
        offset: int = 0,
    ) -> list:
        """Query anchors from disk by flag patterns using json_extract.

        Uses idx_anchors_flags_outcome expression index when outcome filter is set.

        Args:
            outcome: Filter by flags.outcome ('pending','success','failure','neutral',
                     'abandoned'). None = no filter.
            multi_session: Filter by flags.multi_session. None = no filter.
                           NOTE (T1): bool is converted to int (1/0) — SQLite json_extract
                           returns integers for JSON booleans, not Python bools.
            anchor_type: Filter by anchor_type column. None = no filter.
            session_id: Filter by session_id column. None = no filter.
            decay_level_max: Inclusive upper bound on decay_level (0–3).
            limit: Page size for iterative deepening.
            offset: Pagination offset for iterative deepening.

        Returns:
            List of Anchor objects, ordered by last_accessed_at DESC.
        """
        import numpy as np
        from ..subconscious.anchor import Anchor

        conditions = ["decay_level <= ?"]
        params: list = [decay_level_max]

        if outcome is not None:
            conditions.append("json_extract(flags, '$.outcome') = ?")
            params.append(outcome)

        if multi_session is not None:
            # T1 fix: json_extract returns 1/0 for JSON true/false
            conditions.append("json_extract(flags, '$.multi_session') = ?")
            params.append(1 if multi_session else 0)

        if anchor_type is not None:
            conditions.append("anchor_type = ?")
            params.append(anchor_type)

        if session_id is not None:
            conditions.append("session_id = ?")
            params.append(session_id)

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        sql = (
            f"SELECT anchor_id, session_id, anchor_type, brief, key_facts, flags, "
            f"decay_level, access_count, last_accessed_at, t_rel, created_at, updated_at, "
            f"embedding "
            f"FROM anchors "
            f"WHERE {where} "
            f"ORDER BY last_accessed_at DESC "
            f"LIMIT ? OFFSET ?"
        )

        results = []
        try:
            async with self.db.execute(sql, params) as cursor:
                async for row in cursor:
                    emb = None
                    if row[12] is not None:
                        try:
                            emb = np.frombuffer(row[12], dtype=np.float16).astype(np.float32)
                        except Exception:
                            pass
                    results.append(Anchor(
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
                        embedding=emb,
                    ))
        except Exception as e:
            logger.error("find_anchors_by_flags failed: %s", e)
        return results

    async def find_sessions_by_flags(
        self,
        importance: Optional[str] = None,
        urgency: Optional[str] = None,
        has_tag: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list:
        """Query SessionBriefs from disk by field/tag patterns.

        Uses indexed columns (importance, urgency) directly.
        For has_tag: uses json_each() on SQLite 3.38.0+, falls back to LIKE
        on older versions (T2 fix). Fallback warning logged once per process.

        Args:
            importance: Filter by importance column. None = no filter.
            urgency: Filter by urgency column. None = no filter.
            has_tag: Tags JSON array must contain this string. None = no filter.
            limit: Page size.
            offset: Pagination offset.

        Returns:
            List of SessionBrief objects ordered by created_at DESC.
        """
        from ..memory.session_index import SessionBrief
        import numpy as np
        import sqlite3

        conditions = []
        params: list = []

        if importance is not None:
            conditions.append("s.importance = ?")
            params.append(importance)

        if urgency is not None:
            conditions.append("s.urgency = ?")
            params.append(urgency)

        if has_tag is not None:
            # T2: json_each() available only in SQLite 3.38.0+
            sqlite_ver = tuple(int(x) for x in sqlite3.sqlite_version.split("."))
            if sqlite_ver >= (3, 38, 0):
                conditions.append(
                    "EXISTS (SELECT 1 FROM json_each(s.tags) WHERE value = ?)"
                )
                params.append(has_tag)
            else:
                if not getattr(self, "_json_each_warned", False):
                    logger.warning(
                        "find_sessions_by_flags: SQLite %s < 3.38.0, "
                        "json_each() unavailable — using LIKE fallback for tag search",
                        sqlite3.sqlite_version,
                    )
                    self._json_each_warned = True
                conditions.append('s.tags LIKE ?')
                params.append(f'%"{has_tag}"%')

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.extend([limit, offset])

        sql = (
            f"SELECT s.session_id, s.created_at, s.importance, s.tags, s.brief, "
            f"s.conflict, s.urgency, s.deadline_ts, s.urgency_expired, s.bare_entity, "
            f"s.implicit_score, s.resolution, s.intensity, s.embedding "
            f"FROM sessions s "
            f"{where} "
            f"ORDER BY s.created_at DESC "
            f"LIMIT ? OFFSET ?"
        )

        results = []
        try:
            async with self.db.execute(sql, params) as cursor:
                async for row in cursor:
                    embedding = None
                    if row[13] is not None:
                        try:
                            embedding = np.frombuffer(row[13], dtype=np.float16)
                        except Exception:
                            pass
                    results.append(SessionBrief(
                        session_id=row[0],
                        created_at=row[1],
                        importance=row[2],
                        tags=json.loads(row[3]),
                        brief=row[4],
                        score=0.0,
                        resolution=row[11] if row[11] is not None else 1.0,
                        conflict_flag=bool(row[5]),
                        urgency=row[6],
                        deadline_ts=row[7],
                        urgency_expired=bool(row[8]),
                        bare_entity=bool(row[9]),
                        embedding=embedding,
                        implicit_score=row[10] if row[10] is not None else 0.5,
                        intensity=row[12] if row[12] is not None else 0.0,
                        embedding_model_version="multilingual-e5-small",
                    ))
        except Exception as e:
            logger.error("find_sessions_by_flags failed: %s", e)
        return results

    async def get_full_session(self, session_id: str) -> Optional[dict]:
        """Load full session record from SQLite including content_full.
        
        Returns dict matching tool expectations or None.
        """
        try:
            async with self.db.execute(
                """SELECT session_id, brief, why_log, content_full, tags,
                          importance, created_at, conflict
                   FROM sessions WHERE session_id = ?""",
                (session_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row is None:
                    return None
                
                try:
                    tags_val = json.loads(row[4]) if row[4] else []
                except Exception:
                    tags_val = []

                return {
                    "session_id": row[0],
                    "brief": row[1],
                    "why_log": row[2],
                    "content_full": row[3],
                    "tags": tags_val,
                    "importance": row[5],
                    "created_at": row[6],
                    "conflict": bool(row[7]),
                }
        except Exception as e:
            logger.error(f"get_full_session: db error for {session_id}: {e}")
            return None

    async def list_recent_sessions(self, cutoff_ts: float, sql_field: str, limit: int) -> list[dict]:
        """List sessions observed or accessed within the last N days."""
        results: list[dict] = []
        try:
            async with self.db.execute(
                f"""SELECT session_id, brief, importance, created_at,
                           last_use_ts, tags, resolution
                    FROM sessions
                    WHERE {sql_field} >= ?
                    ORDER BY {sql_field} DESC
                    LIMIT ?""",
                (cutoff_ts, limit)
            ) as cursor:
                rows = await cursor.fetchall()
            
            now = time.time()
            for row in rows:
                try:
                    tags = json.loads(row[5]) if row[5] else []
                except Exception:
                    tags = []
                age_days = (now - row[3]) / 86400
                results.append({
                    "session_id": row[0],
                    "brief": row[1],
                    "importance": row[2],
                    "created_at": row[3],
                    "last_accessed_at": row[4] or row[3],
                    "age_days": round(age_days, 2),
                    "resolution": row[6] if row[6] is not None else 1.0,
                    "tags": tags,
                })
        except Exception as e:
            logger.error(f"list_recent_sessions: SQLite error: {e}")
            
        return results

    async def list_precision_entries(
        self,
        precision_type: Optional[str] = None,
        importance: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """Read precision artifacts from SQLite precision_log table."""
        conditions = []
        params: List[Any] = []
        if precision_type:
            conditions.append("type = ?")
            params.append(precision_type)
        if importance:
            conditions.append("importance = ?")
            params.append(importance)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.append(limit)

        try:
            async with self.db.execute(
                f"""SELECT precision_id, session_id, type, value, context_tag, importance, created_at
                    FROM precision_log {where} ORDER BY created_at DESC LIMIT ?""",
                params
            ) as cursor:
                rows = await cursor.fetchall()
        except Exception as e:
            logger.error(f"list_precision_entries: db error: {e}")
            return []

        return [
            {
                "precision_id": r[0],
                "session_id": r[1],
                "type": r[2],
                "value": r[3],
                "context_tag": r[4],
                "importance": r[5],
                "created_at": r[6],
            }
            for r in rows
        ]

    async def search_sessions_by_time(self, lo: int, hi: int, limit: int) -> list[dict]:
        """Find sessions WHERE created_at >= lo AND created_at < hi. Uses idx_sessions_date."""
        results: list[dict] = []
        try:
            async with self.db.execute(
                """SELECT session_id, brief, importance, created_at, tags
                   FROM sessions
                   WHERE created_at >= ? AND created_at < ?
                   ORDER BY created_at ASC
                   LIMIT ?""",
                (lo, hi, limit)
            ) as cursor:
                async for row in cursor:
                    try:
                        tags = json.loads(row[4]) if row[4] else []
                    except Exception:
                        tags = []
                    results.append({
                        "session_id": row[0],
                        "brief": row[1],
                        "importance": row[2],
                        "created_at": row[3],
                        "tags": tags,
                    })
        except Exception as e:
            logger.error(f"search_sessions_by_time({lo}, {hi}, {limit}): {e}")
        return results

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
        import numpy as np
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
                         use_count, deep_use_count, last_use_ts, implicit_score,
                         resolution, intensity)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                            session.embedding.astype(np.float16).tobytes() if session.embedding is not None else None,
                            getattr(session, 'use_count', 0),
                            getattr(session, 'deep_use_count', 0),
                            getattr(session, 'last_use_ts', None),
                            getattr(session, 'implicit_score', 0.5),
                            getattr(session, 'resolution', 1.0),
                            getattr(session, 'intensity', 0.0),
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


        # Log storage flush (v1.0 spec — Point #15)
        if self.ctx is not None:
            pass

        logger.debug(f"Flushed {len(batch)} sessions to SQLite")


# Backward compatibility alias
    async def delete_anchors_by_session(self, session_id: str) -> None:
        """Delete all anchors associated with a specific session."""
        try:
            await self.db.execute("DELETE FROM anchors WHERE session_id = ?", (session_id,))
            await self.db.commit()
            logger.info(f"Anchors for session {session_id} deleted from SQLite")
        except Exception as e:
            logger.error(f"Failed to delete anchors for session {session_id}: {e}")
            raise

SQLiteStorage = DatabaseManager
