# SPDX-License-Identifier: FSL-1.1-MIT
"""Mock embedding engine for tests — zero dependencies, instant."""
import numpy as np


class MockEmbeddingEngine:
    """Deterministic mock for testing. No ONNX, no tokenizer.
    
    Returns consistent vectors based on text hash.
    Satisfies EmbeddingEngine protocol.
    """
    
    def __init__(self, dim: int = 768):
        self._dim = dim
    
    @property
    def dim(self) -> int:
        return self._dim
    
    def encode(self, text: str, max_length: int = None) -> np.ndarray:
        """Deterministic pseudo-embedding from text hash."""
        rng = np.random.RandomState(hash(text) % 2**31)
        vec = rng.randn(self._dim).astype(np.float32)
        vec = vec / np.linalg.norm(vec)
        return vec.astype(np.float16)
    
    async def aencode(self, text: str, max_length: int = None) -> np.ndarray:
        return self.encode(text, max_length)
    
    def close(self) -> None:
        pass
    
    def __repr__(self) -> str:
        return f"MockEmbeddingEngine(dim={self._dim})"
