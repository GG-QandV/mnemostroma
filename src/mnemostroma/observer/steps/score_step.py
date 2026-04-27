# src/mnemostroma/observer/steps/score_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import time
import logging
import numpy as np
from typing import TYPE_CHECKING
from .base import PipelineContext
from ...memory.scoring import calculate_score, get_importance_weight
from ...storage.log_writer import log_event

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mnemostroma.observer.steps.score")


class ScoreStep:
    """Step 5: Calculate session score (Profile A: Write)."""

    async def run(self, pctx: PipelineContext) -> PipelineContext:
        score_start = time.time()
        
        # Calculate Relevance
        relevance = 0.5
        # Use float32 embedding from metadata for dot product
        embedding_f32 = pctx.metadata.get("embedding_f32")
        if pctx.event.intent_vector is not None and embedding_f32 is not None:
            relevance = float(np.dot(embedding_f32, pctx.event.intent_vector))
            
        created_at = int(time.time())
        pctx.metadata["created_at"] = created_at
        
        # Mapping float importance to string if not already set
        importance_str = pctx.importance or "background"

        # Calculate R, T, I components for logging
        I = get_importance_weight(importance_str, pctx.ctx)
        T = 1.0  # New session

        pctx.score = await calculate_score(
            relevance,
            created_at,
            importance_str,
            pctx.ctx,
            profile="write"
        )

        # Log Score (v1.0 Point #4) — only anomalies in safe mode, all in debug
        _log_cfg = getattr(getattr(pctx.ctx, "config", None), "logging", None)
        _log_mode = getattr(_log_cfg, "mode", "safe")
        _is_anomaly = pctx.score < 0.25 or pctx.score > 0.95
        if _log_mode == "debug" or _is_anomaly:
            await log_event(pctx.ctx, "observer.score", "calculate", {
                "R": round(relevance, 3),
                "T": round(T, 3),
                "I": round(I, 3),
                "score": round(pctx.score, 3),
                "profile": "write",
                "alpha": 0.5, "beta": 0.3, "gamma": 0.2,
            }, latency_ms=(time.time() - score_start) * 1000,
               session_id=pctx.event.session_id,
               level="DEBUG" if not _is_anomaly else "WARNING")
        
        return pctx
