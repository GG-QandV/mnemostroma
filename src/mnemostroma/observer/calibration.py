# SPDX-License-Identifier: FSL-1.1-MIT
"""Onboarding calibration — Phase 1 (passive threshold learning).

Passively records cosine distances between consecutive sessions.
After min_onboarding_sessions, computes continuation_threshold and
writes it back to config.json. No imports, no user action required.
"""
import json
import logging
from pathlib import Path
from typing import List, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.calibration")


class CalibrationCollector:
    """Passive observer that calibrates continuation_threshold over first N sessions.

    Hooks into pipeline after each HNSW add_items call.
    Once calibration_complete=True in config, becomes a no-op.
    """

    def __init__(self, ctx: "SystemContext", config_path: str = "config.json"):
        self.ctx = ctx
        self.config_path = Path(config_path)
        self._distances: List[float] = []
        self._calibrated: bool = ctx.config.calibration.calibration_complete

    def record(self, new_vector: np.ndarray) -> None:
        """Record nearest-neighbor distance for the just-added vector.

        Must be called INSIDE index_lock (after add_items, index already contains new vector).
        Nearest neighbor = most similar previous session (excluding self at distance ~0).
        """
        if self._calibrated:
            return

        count = self.ctx.session_index.get_current_count() if self.ctx.session_index else 0
        if count < 2:
            return

        try:
            # k=2: self (d≈0) + nearest real neighbor
            vec = new_vector.astype(np.float32).flatten().reshape(1, -1)
            labels, distances = self.ctx.session_index.knn_query(vec, k=2)
            # distances are cosine distances (0=identical, 2=opposite)
            # knn_query returns flat lists — skip self (d < 0.001)
            real = [float(d) for d in distances if d > 0.001]
            if real:
                self._distances.append(min(real))
        except Exception as e:
            logger.debug(f"CalibrationCollector.record skipped: {e}")
            return

        min_sessions = self.ctx.config.calibration.min_onboarding_sessions
        if len(self._distances) >= min_sessions:
            self._finalize()

    def _finalize(self) -> None:
        """Compute threshold from collected distances and persist to config.json."""
        distances = sorted(self._distances)
        # P25: bottom quartile = "clearly same topic" boundary
        p25_idx = max(0, int(len(distances) * 0.25) - 1)
        # cosine distance → similarity: threshold = 1 - distance
        raw = 1.0 - distances[p25_idx]
        threshold = round(max(0.70, min(0.92, raw)), 3)

        old_threshold = getattr(self.ctx.config.calibration, 'continuation_threshold', None)
        self._write_config(threshold)
        self._calibrated = True
        logger.info(
            "Onboarding complete: continuation_threshold=%.3f (from %d samples)",
            threshold, len(self._distances),
        )
        # Log calibration event for watch/dashboard observability
        try:
            from ..storage.log_writer import log_event
            import asyncio
            asyncio.ensure_future(
                log_event(self.ctx, "calibration.update", "finalize", {
                    "threshold_old": old_threshold,
                    "threshold_new": threshold,
                    "samples": len(self._distances),
                    "p25_distance": round(distances[max(0, int(len(distances)*0.25)-1)], 4),
                })
            )
        except Exception:
            pass

    def _write_config(self, threshold: float) -> None:
        """Persist calibrated threshold to config.json."""
        if not self.config_path.exists():
            logger.warning("CalibrationCollector: config.json not found, skipping write")
            return
        try:
            data = json.loads(self.config_path.read_text(encoding="utf-8"))
            data.setdefault("calibration", {})
            data["calibration"]["continuation_threshold"] = threshold
            data["calibration"]["calibration_complete"] = True
            self.config_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as e:
            logger.error("CalibrationCollector: failed to write config: %s", e)
