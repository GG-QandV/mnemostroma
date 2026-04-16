# SPDX-License-Identifier: FSL-1.1-MIT
import logging
import time
from typing import Any

logger = logging.getLogger("mnemostroma.tuner.drift")

async def check_drift(tag: str, drift_score: float, threshold: float, ctx: Any):
    """Check for semantic drift in a specific tag and log the event.

    Compliance with v1.0 Logging Spec — Point #7.

    Logs:
    - START: tag, threshold
    - CHECK: drift_score, comparison, result
    - END: flagged status
    """
    start_ms = time.time() * 1000

    # Log START
    if hasattr(ctx, "log_writer") and ctx.log_writer:
        from ..storage.log_writer import log_event
        await log_event(ctx, "tuner.drift", "start", {
            "tag": tag,
            "threshold": threshold,
        })

    flagged = drift_score > threshold

    # Log CHECK result
    if hasattr(ctx, "log_writer") and ctx.log_writer:
        from ..storage.log_writer import log_event
        latency = (time.time() * 1000) - start_ms
        await log_event(ctx, "tuner.drift", "check", {
            "tag": tag,
            "drift_score": round(drift_score, 4),
            "threshold": threshold,
            "drift_exceeds_threshold": flagged,
            "margin": round(drift_score - threshold, 4),
            "flagged": flagged,
        }, latency_ms=latency)

    if flagged:
        logger.warning(f"Semantic drift detected for tag {tag}: {drift_score:.2f} > {threshold}")
