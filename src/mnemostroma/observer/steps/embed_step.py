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


# A paste of a whole file can be arbitrarily long, and every chunk costs one encoder
# pass in the observer's hot path. The cap bounds that work; hitting it is logged with
# the numbers, because silently dropping the tail is the defect this whole step fixes.
MAX_CHUNKS_PER_SESSION = 32


class EmbedStep:
    """Step 1 Embed: session vector plus, for long texts, one vector per chunk.

    A single vector for a long text answers "what is this session about" and nothing
    finer: everything past the model window used to be truncated away. Chunk vectors
    are the second level of the index — they answer "where exactly", while the session
    vector stays what it was, the aggregate.
    """

    async def run(self, pctx: PipelineContext) -> PipelineContext:
        stripped = pctx.metadata.get("stripped", pctx.event.text.strip())

        if not (pctx.ctx.models and pctx.ctx.models.embedder):
            pctx.embedding = None
            return pctx

        embedder = pctx.ctx.models.embedder
        try:
            from ...models.embedding_utils import chunk_content

            chunks = chunk_content(
                stripped, "text", tokenizer=getattr(embedder, "tokenizer", None)
            )

            if len(chunks) > MAX_CHUNKS_PER_SESSION:
                logger.warning(
                    "observer: text yields %d chunks, keeping %d — tail not indexed",
                    len(chunks), MAX_CHUNKS_PER_SESSION,
                )
                pctx.ctx.metrics["chunk_cap_hits"] = (
                    pctx.ctx.metrics.get("chunk_cap_hits", 0) + 1
                )
                chunks = chunks[:MAX_CHUNKS_PER_SESSION]

            if len(chunks) <= 1:
                # Short text: one pass, exactly as before. No chunk vectors — they
                # would duplicate the session vector and double the index for nothing.
                raw = await embedder.aencode(stripped)
                vec = np.array(raw, dtype=np.float32).flatten()
            else:
                chunk_vectors = []
                for chunk in chunks:
                    raw = await embedder.aencode(chunk)
                    chunk_vectors.append(np.array(raw, dtype=np.float32).flatten())

                # The session vector keeps its old meaning — the aggregate — so
                # continuation, conflict and scoring see what they saw before.
                stacked = np.mean(chunk_vectors, axis=0)
                norm = np.linalg.norm(stacked)
                vec = stacked / norm if norm > 1e-9 else stacked
                pctx.metadata["chunk_vectors_f32"] = chunk_vectors

            # USER: "embedding: bytes | None" in PipelineContext
            pctx.embedding = vec.astype(np.float16).tobytes()
            # Store redundant float32 for downstream tasks in pctx Metadata
            # (tuner/continuation might need it)
            pctx.metadata["embedding_f32"] = vec
        except Exception as e:
            logger.warning(f"observer: pre-embed failed: {e}")
            pctx.embedding = None
            pctx.metadata.pop("chunk_vectors_f32", None)

        return pctx
