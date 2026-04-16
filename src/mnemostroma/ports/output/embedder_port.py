# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from mnemostroma.domain.types import Result, EmbedderError

class EmbedderPort(Protocol):
    def embed(self, text: str) -> "Result[bytes, EmbedderError]": ...
    def embed_batch(self, texts: list[str]) -> "Result[list[bytes], EmbedderError]": ...

    @property
    def dim(self) -> int: ...  # 384 or 512
