# src/mnemostroma/adapters/sqlite/anchor_repo.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from mnemostroma.domain.types import StorageError, err, ok

if TYPE_CHECKING:
    from mnemostroma.domain.types import Result
    from mnemostroma.storage.sqlite import SQLiteStorage
    from mnemostroma.subconscious.anchor import Anchor


class AnchorRepo:
    """Adapter for AnchorPort using SQLiteStorage (DatabaseManager)."""

    def __init__(self, storage: SQLiteStorage) -> None:
        self._storage = storage

    async def save(self, anchor: Anchor) -> Result[None, StorageError]:
        try:
            await self._storage.save_anchor(anchor)
            return ok(None)
        except Exception as e:
            return err(StorageError(f"Failed to save anchor: {e}"))

    async def load_by_type(
        self, anchor_type: str, session_id: str | None, limit: int
    ) -> Result[list[Anchor], StorageError]:
        try:
            # find_anchors_by_flags correctly filters by session_id=None (all) or specific ID
            anchors = await self._storage.find_anchors_by_flags(
                anchor_type=anchor_type,
                session_id=session_id,
                limit=limit
            )
            return ok(anchors)
        except Exception as e:
            return err(StorageError(f"Failed to load anchors by type '{anchor_type}': {e}"))

    async def delete_by_session(self, session_id: str) -> Result[None, StorageError]:
        try:
            await self._storage.delete_anchors_by_session(session_id)
            return ok(None)
        except Exception as e:
            return err(StorageError(f"Failed to delete anchors for session {session_id}: {e}"))
