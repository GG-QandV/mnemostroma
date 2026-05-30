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
                pctx.entities = await pctx.ctx.models.ner.extract_entities(
                    pctx.event.text,
                    threshold=pctx.ctx.config.importance.ner_score_threshold
                )
            except Exception as e:
                logger.warning(f"observer: pre-ner failed: {e}")
                pctx.entities = []
            finally:
                # Lazy-unload: free ~200 MB ONNX session after each run.
                # Model reloads automatically on next extract_entities() call.
                try:
                    pctx.ctx.models.ner.unload()
                except Exception:
                    pass
        else:
            pctx.entities = []
            
        return pctx
