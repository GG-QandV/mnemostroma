# SPDX-License-Identifier: FSL-1.1-MIT
"""Matrix cosine search — replaces hnswlib (ADR-002).

Language-agnostic: e5-small embeddings work across all languages.
API is drop-in compatible with the former HNSWIndex wrapper.
"""
import math
import time
from pathlib import Path
from typing import Any

import numpy as np


def time_decay(age_days: float, half_life: float) -> float:
    """Exponential recency decay factor.

    At age=0 returns 1.0 (no penalty).
    At age=half_life returns 0.5.
    At age=2*half_life returns 0.25.

    Args:
        age_days: Age of the item in days.
        half_life: Days until score is halved.

    Returns:
        Multiplier in (0, 1].
    """
    if half_life <= 0:
        return 1.0
    return math.exp(-age_days * math.log(2) / half_life)


class MatrixSearch:
    """Cosine nearest-neighbour search over a float32 embedding matrix.

    Stores L2-normalised vectors; knn_query returns cosine distances
    (1 - similarity) to match the hnswlib cosine-space convention so all
    callers using ``1.0 - dist`` keep working without changes.
    """

    def __init__(self, dim: int, max_elements: int = 10000, **kwargs):
        self.dim = dim
        self._max_elements = max_elements
        self._vectors: np.ndarray = np.empty((0, dim), dtype=np.float32)
        self._labels: list[int] = []

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def add_items(self, vectors: list[np.ndarray], ids: list[int]) -> None:
        """Append normalised vectors and their integer labels."""
        vecs = np.array(vectors, dtype=np.float32).reshape(-1, self.dim)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms < 1e-9, 1.0, norms)
        vecs = vecs / norms
        self._vectors = np.vstack([self._vectors, vecs]) if len(self._vectors) else vecs
        self._labels.extend(ids)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def knn_query(
        self,
        vector: np.ndarray,
        k: int = 5,
        time_weighted: bool = False,
        half_life_days: float = 30.0,
        exempt_importance: tuple = ("critical", "principle"),
        label_meta: dict | None = None,
    ) -> tuple[list[int], list[float]]:
        """Return (labels, distances) for the k nearest neighbours.

        distances are cosine distances: 0 = identical, 2 = opposite.
        Callers using ``cosine = 1.0 - dist`` stay correct.

        Args:
            vector: Query embedding.
            k: Number of results.
            time_weighted: If True, apply recency decay to scores.
            half_life_days: Half-life for time decay (only when time_weighted=True).
            exempt_importance: Importance values exempt from time decay.
            label_meta: Dict[label -> SessionBrief] for time_weighted scoring.
        """
        count = len(self._labels)
        if count == 0:
            return [], []

        k = min(k, count)
        vec = np.array(vector, dtype=np.float32).flatten()
        norm = np.linalg.norm(vec)
        if norm > 1e-9:
            vec = vec / norm

        # cosine similarity via dot product (both sides normalised)
        sims = self._vectors @ vec          # shape [N]

        # Optional time-weighted scoring (Phase 11.B)
        if time_weighted and label_meta:
            now = time.time()
            weighted = sims.copy()
            for i, label in enumerate(self._labels):
                sb = label_meta.get(label)
                if sb is None:
                    continue
                importance = getattr(sb, "importance", "normal")
                if importance in exempt_importance:
                    continue  # exempt — no decay
                age_days = (now - sb.created_at) / 86400
                weighted[i] *= time_decay(age_days, half_life_days)
            dists = 1.0 - weighted
        else:
            dists = 1.0 - sims

        idx = np.argsort(dists)[:k]
        labels = [self._labels[i] for i in idx]
        distances = dists[idx].tolist()
        return labels, distances

    # ------------------------------------------------------------------
    # Capacity helpers (kept for backward-compat with callers)
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset matrix and labels — used after batch eviction to remove stale vectors."""
        self._vectors = np.empty((0, self.dim), dtype=np.float32)
        self._labels = []

    def get_current_count(self) -> int:
        return len(self._labels)

    def get_max_elements(self) -> int:
        return max(self._max_elements, len(self._labels) + 1000)

    def resize_index(self, new_max: int) -> None:
        """No-op — numpy matrix grows dynamically."""
        self._max_elements = new_max

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_index(self, path: str | Path) -> None:
        base = str(path)
        np.save(base + ".vecs.npy", self._vectors)
        np.save(base + ".labels.npy", np.array(self._labels, dtype=np.int64))

    def load_index(self, path: str | Path, max_elements: int = 0) -> None:
        base = str(path)
        vecs_path = Path(base + ".vecs.npy")
        labels_path = Path(base + ".labels.npy")
        if vecs_path.exists() and labels_path.exists():
            self._vectors = np.load(str(vecs_path))
            self._labels = np.load(str(labels_path)).tolist()
            if max_elements:
                self._max_elements = max_elements


# Aliases kept so imports of the old name still work
HNSWIndex = MatrixSearch


def init_session_index(config: Any) -> MatrixSearch:
    """Initialize matrix search index for sessions from config."""
    return MatrixSearch(
        dim=config.search.embedding_dim,
        max_elements=10000,
    )


def init_content_index(config: Any) -> MatrixSearch:
    """Initialize matrix search index for content blocks from config."""
    return MatrixSearch(
        dim=config.search.embedding_dim,
        max_elements=5000,
    )
