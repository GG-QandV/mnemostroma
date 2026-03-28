# SPDX-License-Identifier: FSL-1.1-MIT
import hnswlib
import numpy as np
from pathlib import Path
from typing import List, Tuple, Optional, Any

class HNSWIndex:
    """HNSWlib wrapper for ANN vector search."""
    def __init__(
        self, 
        dim: int, 
        max_elements: int, 
        space: str = 'cosine',
        M: int = 16,
        ef_construction: int = 200
    ):
        self.dim = dim
        self.index = hnswlib.Index(space=space, dim=dim)
        self.index.init_index(max_elements=max_elements, ef_construction=ef_construction, M=M)
        self.index.set_ef(100) # Default ef for queries

    def add_items(self, vectors: List[np.ndarray], ids: List[int]):
        """Add vectors to the index."""
        self.index.add_items(np.array(vectors), np.array(ids))

    def knn_query(self, vector: np.ndarray, k: int = 5) -> Tuple[List[int], List[float]]:
        """Search for top-K nearest neighbors.
        
        Returns:
            Tuple of (labels, distances).
        """
        labels, distances = self.index.knn_query(vector, k=k)
        return labels[0].tolist(), distances[0].tolist()

    def save_index(self, path: str | Path):
        """Persist index to disk."""
        self.index.save_index(str(path))

    def load_index(self, path: str | Path, max_elements: int):
        """Load index from disk."""
        self.index.load_index(str(path), max_elements=max_elements)

    def get_current_count(self) -> int:
        """Return number of elements in the index."""
        return self.index.get_current_count()

    def get_max_elements(self) -> int:
        """Return maximum capacity of the index."""
        return self.index.get_max_elements()

def init_session_index(config: Any) -> HNSWIndex:
    """Initialize HNSW index for sessions from config."""
    return HNSWIndex(
        dim=config.hnsw.embedding_dim,
        max_elements=config.hnsw.session_max_elements,
        M=config.hnsw.session_M,
        ef_construction=config.hnsw.session_ef_construction
    )

def init_content_index(config: Any) -> HNSWIndex:
    """Initialize HNSW index for content blocks from config."""
    # Content branch requires higher precision (M=32, ef=400)
    return HNSWIndex(
        dim=config.hnsw.embedding_dim,
        max_elements=config.hnsw.content_max_elements,
        M=32, 
        ef_construction=400
    )
