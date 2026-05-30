# SPDX-License-Identifier: FSL-1.1-MIT
"""Embedding engine protocol — the contract all engines must follow."""
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbeddingEngine(Protocol):
    """Contract for any embedding engine.
    
    Implementations:
        ONNXEmbeddingEngine — local ONNX inference
        MockEmbeddingEngine — testing
        (future) RemoteEmbeddingEngine — HTTP API
    """
    
    @property
    def dim(self) -> int:
        """Embedding dimensionality."""
        ...
    
    def encode(self, text: str) -> np.ndarray:
        """Encode text → normalized float16 vector of shape (dim,).
        
        Blocking. For async context use aencode().
        """
        ...
    
    async def aencode(self, text: str) -> np.ndarray:
        """Non-blocking async encode.
        
        Default: delegates to encode() via executor.
        """
        ...
    
    def close(self) -> None:
        """Release resources (session, executor)."""
        ...
