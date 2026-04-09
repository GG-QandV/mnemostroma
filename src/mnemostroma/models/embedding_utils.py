# SPDX-License-Identifier: FSL-1.1-MIT
"""Embedding utilities — chunking and multi-chunk aggregation.

Engine-agnostic: works with any EmbeddingEngine implementation.
"""
import logging
import numpy as np
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from .protocol import EmbeddingEngine

logger = logging.getLogger(__name__)


def chunk_content(text: str, content_type: str) -> List[str]:
    """Split content into chunks based on type.
    
    Args:
        text: Raw content text.
        content_type: code/text/chapter etc.
        
    Returns:
        List of non-empty text chunks.
    """
    # TODO: AST-aware splitting for code
    paragraphs = text.split("\n\n")
    return [p.strip() for p in paragraphs if p.strip()]


def encode_chunks(
    engine: "EmbeddingEngine",
    chunks: List[str],
    decay: float = 0.2,
    min_weight: float = 0.2,
) -> np.ndarray:
    """Encode multiple chunks and aggregate via weighted mean pooling.
    
    First chunk gets weight 1.0, each subsequent decays by `decay`.
    Minimum weight clamped to `min_weight`.
    
    Args:
        engine: Any EmbeddingEngine instance.
        chunks: Text chunks to encode.
        decay: Weight decay per chunk position.
        min_weight: Minimum weight floor.
        
    Returns:
        Normalized float16 vector of shape (engine.dim,).
    """
    if not chunks:
        return np.zeros(engine.dim, dtype=np.float16)
    
    vectors = []
    for i, chunk in enumerate(chunks):
        vec = engine.encode(chunk)
        weight = max(min_weight, 1.0 - (i * decay))
        vectors.append(vec.astype(np.float32) * weight)
        
        logger.debug(
            "encode_chunks | chunk=%d/%d weight=%.1f",
            i + 1, len(chunks), weight,
        )
    
    aggregated = np.mean(vectors, axis=0)
    
    # L2 normalize
    norm = np.linalg.norm(aggregated)
    if norm > 0:
        aggregated = aggregated / norm
    
    return aggregated.astype(np.float16)


async def aencode_chunks(
    engine: "EmbeddingEngine",
    chunks: List[str],
    decay: float = 0.2,
    min_weight: float = 0.2,
) -> np.ndarray:
    """Async version of encode_chunks."""
    if not chunks:
        return np.zeros(engine.dim, dtype=np.float16)
    
    vectors = []
    for i, chunk in enumerate(chunks):
        vec = await engine.aencode(chunk)
        weight = max(min_weight, 1.0 - (i * decay))
        vectors.append(vec.astype(np.float32) * weight)
    
    aggregated = np.mean(vectors, axis=0)
    norm = np.linalg.norm(aggregated)
    if norm > 0:
        aggregated = aggregated / norm
    
    return aggregated.astype(np.float16)
