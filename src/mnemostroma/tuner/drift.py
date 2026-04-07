# SPDX-License-Identifier: FSL-1.1-MIT
import logging
import time
from typing import Any

logger = logging.getLogger("mnemostroma.tuner.drift")

async def check_drift(tag: str, drift_score: float, threshold: float, ctx: Any):
    """Check for semantic drift in a specific tag and log the event.
    
    Compliance with v1.0 Logging Spec — Point #7.
    """
    flagged = drift_score > threshold
    
    if flagged:
        logger.warning(f"Semantic drift detected for tag {tag}: {drift_score:.2f} > {threshold}")
