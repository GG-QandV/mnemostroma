# src/mnemostroma/adapters/onnx/embedder.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from typing import TYPE_CHECKING
from mnemostroma.domain.types import ok, err, EmbedderError

if TYPE_CHECKING:
    from mnemostroma.models.onnx_engine import ONNXEmbeddingEngine
    from mnemostroma.domain.types import Result


class EmbedderRepo:
    """Adapter for EmbedderPort using ONNXEmbeddingEngine."""

    def __init__(self, engine: "ONNXEmbeddingEngine") -> None:
        self._engine = engine

    def embed(self, text: str) -> "Result[bytes, EmbedderError]":
        try:
            # engine.encode returns float16 np.ndarray
            vec = self._engine.encode(text)
            return ok(vec.tobytes())
        except Exception as e:
            return err(EmbedderError(f"ONNX encode failed: {e}"))

    def embed_batch(self, texts: list[str]) -> "Result[list[bytes], EmbedderError]":
        try:
            results = []
            for text in texts:
                vec = self._engine.encode(text)
                results.append(vec.tobytes())
            return ok(results)
        except Exception as e:
            return err(EmbedderError(f"ONNX batch encode failed: {e}"))

    @property
    def dim(self) -> int:
        return self._engine.dim
