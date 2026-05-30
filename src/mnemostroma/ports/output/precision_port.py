# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from mnemostroma.domain.types import Result, StorageError

class PrecisionPort(Protocol):
    """Port for accessing verbatim precision artifacts (links, formulas, quotes)."""

    async def list_entries(
        self, 
        precision_type: str | None = None, 
        importance: str | None = None, 
        limit: int = 20
    ) -> Result[list[dict], StorageError]:
        """Retrieve precision log entries from disk."""
        ...
