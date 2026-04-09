# SPDX-License-Identifier: FSL-1.1-MIT
"""PersistenceLayer — formal interface for the disk memory layer.

Encapsulates all SQLite access behind two explicit write paths:

  Path 1 — enqueue_session():  queued, 5-second batch cycle.
            Sessions can tolerate up to 5-second loss on crash.

  Path 2 — save_anchor() / save_experience():  guaranteed immediate await.
            These are sacred writes — NEVER lost, pipeline blocks until done.

Also provides:
  - Hydration reads for WorkingMemory bootstrap (startup only)
  - flush() / sync() for explicit drain + WAL checkpoint
"""
import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from .sqlite import DatabaseManager

logger = logging.getLogger("mnemostroma.persistence")


class PersistenceLayer:
    """Disk memory layer interface.

    Single point of contact between WorkingMemory components
    (pipeline, consolidation, dreamer, dissolver) and SQLite storage.
    Eliminates direct DatabaseManager coupling and hasattr guards.

    Args:
        db_manager: Initialized DatabaseManager backend.
    """

    def __init__(self, db_manager: "DatabaseManager") -> None:
        self._db = db_manager

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background flush worker."""
        await self._db.start()

    async def stop(self) -> None:
        """Gracefully stop worker and flush remaining queue."""
        await self._db.stop()

    def wire_ctx(self, ctx: Any) -> None:
        """Wire SystemContext into the backend for log_event access.

        Called by Conductor after ctx is fully initialised.
        """
        self._db.ctx = ctx

    # ------------------------------------------------------------------
    # Write path 1 — queued session writes (5-sec batch, loss ≤5s OK)
    # ------------------------------------------------------------------

    def enqueue_session(self, sb: Any) -> None:
        """Add a SessionBrief to the async flush queue.

        Non-blocking. On QueueFull logs ERROR and increments
        ctx.metrics['dropped_sessions'] (RAM⊆DISK violated).
        """
        self._db.queue_write(sb)

    # ------------------------------------------------------------------
    # Write path 2 — guaranteed immediate writes (NEVER lost)
    # ------------------------------------------------------------------

    async def save_anchor(self, anchor: Any) -> None:
        """Persist anchor to SQLite immediately.

        Sacred write: pipeline blocks until committed.
        Anchors must never be lost — they are the permanent entity layer.
        """
        await self._db.save_anchor(anchor)

    async def save_experience(
        self,
        tag: str,
        session_count: int,
        score_sum: float,
        conflict_count: int,
        last_updated: int,
        emotion_positive: int = 0,
        emotion_negative: int = 0,
        emotion_intensity_sum: float = 0.0,
    ) -> None:
        """Persist experience cluster to SQLite immediately.

        Sacred write: experience markers encode success/failure patterns
        and must not be lost.
        """
        await self._db.upsert_experience(
            tag=tag,
            session_count=session_count,
            score_sum=score_sum,
            conflict_count=conflict_count,
            last_updated=last_updated,
            emotion_positive=emotion_positive,
            emotion_negative=emotion_negative,
            emotion_intensity_sum=emotion_intensity_sum,
        )

    # ------------------------------------------------------------------
    # Flush / sync
    # ------------------------------------------------------------------

    async def flush(self) -> None:
        """Drain the pending session queue immediately.

        Safe to call while worker is running. Used by:
        - Dissolver before eviction (guarantee persistence before RAM wipe)
        - SIGUSR1 handler (on-demand flush via CLI)
        - ctx_evict / admin tools
        """
        await self._db.flush()

    async def sync(self, checkpoint_mode: str = "PASSIVE") -> Dict[str, Any]:
        """Force-flush queue then WAL checkpoint.

        Steps:
        1. Drain queue — wait until worker persists everything (timeout 10s).
        2. WAL checkpoint (PASSIVE = non-blocking, TRUNCATE = shutdown mode).

        Returns:
            dict: flushed_sessions, wal_pages, checkpoint_mode.
        """
        queue_size_before = self._db.queue.qsize()
        try:
            await asyncio.wait_for(self._db.queue.join(), timeout=10.0)
        except asyncio.TimeoutError:
            logger.warning("PersistenceLayer.sync: queue drain timed out after 10s (partial flush)")

        wal_pages = -1
        try:
            async with self._db.db.execute(
                f"PRAGMA wal_checkpoint({checkpoint_mode})"
            ) as cur:
                row = await cur.fetchone()
                if row:
                    wal_pages = row[1] if len(row) > 1 else -1
        except Exception as e:
            logger.error(f"PersistenceLayer.sync: WAL checkpoint failed: {e}")

        stats = {
            "flushed_sessions": queue_size_before,
            "wal_pages": wal_pages,
            "checkpoint_mode": checkpoint_mode,
        }
        logger.info("PersistenceLayer.sync complete: %s", stats)
        return stats

    # ------------------------------------------------------------------
    # Hydration reads — startup only (WorkingMemory bootstrap)
    # ------------------------------------------------------------------

    async def get_all_session_briefs(self) -> List[Any]:
        """Load all session metadata for ram_index hydration."""
        return await self._db.get_all_session_briefs()

    async def get_all_embeddings(self, expected_dim: int) -> List[Any]:
        """Load all session embeddings for MatrixSearch hydration."""
        return await self._db.get_all_embeddings(expected_dim)

    async def get_all_content_embeddings(self, expected_dim: int) -> List[Any]:
        """Load all content embeddings for content_index hydration."""
        return await self._db.get_all_content_embeddings(expected_dim)

    async def load_anchors(self, limit: int = 1000) -> List[Any]:
        """Load most-recently-accessed anchors for anchor_index hydration."""
        return await self._db.load_anchors(limit)

    async def load_experience(self) -> List[dict]:
        """Load all experience clusters for ExperienceIndex hydration."""
        return await self._db.load_experience()

    # ------------------------------------------------------------------
    # Point reads — on-demand cold load
    # ------------------------------------------------------------------

    async def get_session_by_id(self, session_id: str) -> Optional[Any]:
        """Cold-load a single session from SQLite (ctx.load() path)."""
        return await self._db.get_session_by_id(session_id)

    async def get_anchor(self, anchor_id: str) -> Optional[Any]:
        """Load a single anchor by ID."""
        return await self._db.get_anchor(anchor_id)

    def pending_writes(self) -> int:
        """Return current queue depth (pending session writes)."""
        return self._db.queue.qsize()
