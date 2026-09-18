# src/mnemostroma/observer/steps/filter_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ...subconscious.precision_guard import precision_guard
from ..filter import needs_model_ner
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

        # 0.6. NER gate. Model NER is the most expensive step in the pipeline and was
        # running on every observation, while observer.ner_call_rate_target asks for
        # ~0.3. The regex half of HybridNER is unaffected — it is cheap and stays on.
        # Text signals only: ctx.precision_warnings holds cross-session conflicts,
        # not items of this text, and gating on it would make the same text behave
        # differently depending on what came before.
        needs_ner, reason = needs_model_ner(stripped)
        pctx.metadata["needs_ner"] = needs_ner
        pctx.metadata["ner_gate_reason"] = reason

        # tools/logs.py already reads `observer.filter` to report ner_call_rate_actual;
        # until now nothing emitted it, so the rate was never observable.

        return pctx
