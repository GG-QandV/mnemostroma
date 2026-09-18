# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from mnemostroma.domain.types import NotFoundError, StorageError, err, ok

if TYPE_CHECKING:
    from mnemostroma.domain.types import Result
    from mnemostroma.memory.session_index import SessionBrief
    from mnemostroma.storage.sqlite import SQLiteStorage

class SessionRepo:
    """SQLite implementation of the SessionPort.
    
    Delegates all low-level operations to the DatabaseManager (SQLiteStorage)
    and wraps results in the Result[T, E] pattern for domain boundary integrity.
    """
    def __init__(self, storage: SQLiteStorage):
        self._storage = storage

    async def save(self, s: SessionBrief) -> Result[None, StorageError]:
        """Save session metadata to the async flush queue.
        
        Uses queue_write to avoid blocking the critical path.
        """
        try:
            # Note: queue_write is sync but SessionPort requires async interface
            self._storage.queue_write(s)
            return ok(None)
        except Exception as e:
            return err(StorageError(f"Failed to queue session save: {e}"))

    async def load(self, id: str) -> Result[SessionBrief, NotFoundError]:
        """Load a single session by its unique ID."""
        try:
            session = await self._storage.load_session(id)
            if session is None:
                return err(NotFoundError(f"Session {id} not found"))
            return ok(session)
        except Exception as e:
            return err(StorageError(f"Failed to load session {id}: {e}"))

    async def list_by_score(self, limit: int) -> Result[list[SessionBrief], StorageError]:
        """List sessions ordered by score (implicit_score) DESC."""
        try:
            sessions = await self._storage.list_sessions_by_score(limit)
            return ok(sessions)
        except Exception as e:
            return err(StorageError(f"Failed to list sessions by score: {e}"))

    async def delete(self, id: str) -> Result[None, StorageError]:
        """Delete a session by ID."""
        try:
            await self._storage.delete_session(id)
            return ok(None)
        except Exception as e:
            return err(StorageError(f"Failed to delete session {id}: {e}"))

    async def update_score(self, id: str, score: float) -> Result[None, StorageError]:
        """Update the score for a specific session."""
        try:
            await self._storage.update_session_score(id, score)
            return ok(None)
        except Exception as e:
            return err(StorageError(f"Failed to update score for session {id}: {e}"))

    async def list_by_tags(self, tags: list[str], limit: int) -> Result[list[SessionBrief], StorageError]:
        """List sessions containing at least one of the specified tags."""
        try:
            sessions = await self._storage.list_sessions_by_tags(tags, limit)
            return ok(sessions)
        except Exception as e:
            return err(StorageError(f"Failed to list sessions by tags {tags}: {e}"))

    async def load_full(self, id: str) -> Result[dict, StorageError]:
        """Load full session record from SQLite including content_full."""
        try:
            res = await self._storage.get_full_session(id)
            if res is None:
                return err(NotFoundError(f"Session {id} not found"))
            return ok(res)
        except Exception as e:
            return err(StorageError(f"Failed to load full session {id}: {e}"))

    async def load_recent(self, days: float, by: str, limit: int) -> Result[list[dict], StorageError]:
        """List sessions observed or accessed within the last N days."""
        try:
            import time
            cutoff = time.time() - days * 86400
            sql_field = "created_at" if by == "created" else "last_use_ts"
            res = await self._storage.list_recent_sessions(cutoff, sql_field, limit)
            return ok(res)
        except Exception as e:
            return err(StorageError(f"Failed to list recent sessions: {e}"))

    async def search_by_time_window(self, lo: int, hi: int, limit: int) -> Result[list[dict], StorageError]:
        """Search sessions in time window [lo, hi). Delegates to SQLiteStorage."""
        try:
            res = await self._storage.search_sessions_by_time(lo, hi, limit)
            return ok(res)
        except Exception as e:
            return err(StorageError(f"Time window search failed: {e}"))
