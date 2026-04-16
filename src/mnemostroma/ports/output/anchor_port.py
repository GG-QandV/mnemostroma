# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from mnemostroma.domain.types import Result, StorageError
    from mnemostroma.subconscious.anchor import Anchor as AnchorEntry

class AnchorPort(Protocol):
    async def save(self, anchor: "AnchorEntry") -> "Result[None, StorageError]": ...
    async def load_by_type(self, anchor_type: str, session_id: str | None, limit: int
                           ) -> "Result[list[AnchorEntry], StorageError]": ...
    async def delete_by_session(self, session_id: str) -> "Result[None, StorageError]": ...
