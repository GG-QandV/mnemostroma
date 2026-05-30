# src/mnemostroma/observer/steps/filter_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...subconscious.precision_guard import precision_guard
from ..marker import structural_prefilter
from .base import PipelineContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mnemostroma.observer.steps.filter")


class FilterStep:
    """Step 0 & 0.5: Pre-filter and Precision Guard."""

    async def run(self, pctx: PipelineContext) -> PipelineContext:
        text = pctx.event.text
        stripped = text.strip()
        pctx.metadata["stripped"] = stripped
        
        # 0. Sync pre-filter
        if len(stripped) < 5 or not structural_prefilter(stripped):
            pctx.should_abort = True
            return pctx

        # 0.5. Precision Guard
        if pctx.ctx.config.precision_guard.enabled:
            precision_guard(stripped, pctx.ctx)
            
        return pctx
