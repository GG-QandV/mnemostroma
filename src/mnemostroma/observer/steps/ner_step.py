# src/mnemostroma/observer/steps/ner_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .base import PipelineContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mnemostroma.observer.steps.ner")


class NERStep:
    """Step 1 NER: Extract entities using GLiNER."""

    async def run(self, pctx: PipelineContext) -> PipelineContext:
        if pctx.ctx.models and pctx.ctx.models.ner:
            try:
                # The gate decides only whether the MODEL runs; regex patterns still
                # cover decisions, prohibitions, technologies and outcomes.
                use_model = pctx.metadata.get("needs_ner", True)
                pctx.entities = await pctx.ctx.models.ner.extract_entities(
                    pctx.event.text,
                    threshold=pctx.ctx.config.importance.ner_score_threshold,
                    use_model=use_model,
                )
            except Exception as e:
                logger.warning(f"observer: pre-ner failed: {e}")
                pctx.entities = []
        else:
            pctx.entities = []
            
        return pctx
