# src/mnemostroma/observer/steps/embed_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from .base import PipelineContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mnemostroma.observer.steps.embed")


class EmbedStep:
    """Step 1 Embed: Generate session embedding via ONNX."""

    async def run(self, pctx: PipelineContext) -> PipelineContext:
        stripped = pctx.metadata.get("stripped", pctx.event.text.strip())
        
        if pctx.ctx.models and pctx.ctx.models.embedder:
            try:
                # original pipeline used aencode (async wrapper around onnx run)
                raw = await pctx.ctx.models.embedder.aencode(stripped)
                vec = np.array(raw, dtype=np.float32).flatten()
                
                # USER: "embedding: bytes | None" in PipelineContext
                pctx.embedding = vec.astype(np.float16).tobytes()
                
                # Store redundant float32 for downstream tasks in pctx Metadata
                # (tuner/continuation might need it)
                pctx.metadata["embedding_f32"] = vec
            except Exception as e:
                logger.warning(f"observer: pre-embed failed: {e}")
                pctx.embedding = None
        else:
            pctx.embedding = None
            
        return pctx
