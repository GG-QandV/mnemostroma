# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from typing import TYPE_CHECKING

from mnemostroma.domain.types import StorageError, err, ok

if TYPE_CHECKING:
    from mnemostroma.domain.types import Result
    from mnemostroma.storage.sqlite import SQLiteStorage

class PrecisionRepo:
    """SQLite implementation of the PrecisionPort.
    
    Provides access to verbatim precision artifacts via the DatabaseManager.
    """
    def __init__(self, storage: SQLiteStorage):
        self._storage = storage

    async def list_entries(
        self, 
        precision_type: str | None = None, 
        importance: str | None = None, 
        limit: int = 20
    ) -> Result[list[dict], StorageError]:
        """Retrieve precision log entries from disk."""
        try:
            res = await self._storage.list_precision_entries(
                precision_type=precision_type,
                importance=importance,
                limit=limit
            )
            return ok(res)
        except Exception as e:
            return err(StorageError(f"Failed to list precision entries: {e}"))
