# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
import time

import numpy as np

from ..core import SystemContext
from ..memory.session_index import SessionBrief
from .entities import MarkerAction, SourceType
from .filter import CONFLICT, detect_urgency
from .marker import marker as _marker
from .steps.base import IOEvent, PipelineContext
from .steps.embed_step import EmbedStep
from .steps.filter_step import FilterStep
from .steps.ner_step import NERStep
from .steps.persist_step import PersistStep
from .steps.score_step import ScoreStep

logger = logging.getLogger("mnemostroma.observer")


def _float_to_importance(importance: float) -> str:
    """Map marker entity importance float → legacy string label."""
    if importance >= 1.0:
        return "principle"
    if importance >= 0.88:
        return "critical"
    if importance >= 0.55:
        return "important"
    return "background"


async def observer_pipeline(
    text: str, 
    session_id: str, 
    ctx: SystemContext,
    intent_vector: np.ndarray | None = None
) -> SessionBrief | None:
    """Process agent output through the modular StepChain.
    
    Budget: 40ms. Parallel NER/Embed preserved via asyncio.gather.
    """
    event = IOEvent(text=text, session_id=session_id, intent_vector=intent_vector)
    pctx = PipelineContext(event=event, ctx=ctx)
    
    # Init steps
    filter_step = FilterStep()
    ner_step = NERStep()
    embed_step = EmbedStep()
    score_step = ScoreStep()
    persist_step = PersistStep()

    # 1. Filter Step (Step 0 & 0.5)
    await filter_step.run(pctx)
    if pctx.should_abort:
        return None

    # 2. Parallel NER + Embed (Step 1)
    # Orchestrator handles parallelism to maintain latency budget.
    ner_pctx = PipelineContext(event=event, ctx=ctx)
    embed_pctx = PipelineContext(event=event, ctx=ctx)
    
    # Share 'stripped' from first step
    ner_pctx.metadata["stripped"] = pctx.metadata["stripped"]
    embed_pctx.metadata["stripped"] = pctx.metadata["stripped"]

    pipe_start = time.time()
    await asyncio.gather(
        ner_step.run(ner_pctx),
        embed_step.run(embed_pctx)
    )

    if ner_pctx.should_abort or embed_pctx.should_abort:
        return None

    # Merge results into main pctx (USER Refinement 2)
    pctx.entities = ner_pctx.entities
    pctx.embedding = embed_pctx.embedding
    # Also merge f32 embedding for downstream components
    pctx.metadata["embedding_f32"] = embed_pctx.metadata.get("embedding_f32")


    # Fallback embedding if pre-embed failed
    embedding_f32 = pctx.metadata.get("embedding_f32")
    if embedding_f32 is None:
        dim = ctx.config.search.embedding_dim
        v = np.random.rand(dim).astype(np.float32)
        embedding_f32 = v / np.linalg.norm(v)
        pctx.metadata["embedding_f32"] = embedding_f32

    # 3. Anchor Guardian & Surfacing (Phase 11.A/C/E)
    if embedding_f32 is not None and (
        ctx.config.anchor_guardian.enabled
        or ctx.config.associative_surfacing.enabled
        or ctx.config.open_loop.enabled
    ):
        tasks = []
        if ctx.config.anchor_guardian.enabled:
            from ..subconscious.guardian import anchor_guardian
            tasks.append(anchor_guardian(embedding_f32, ctx, 
                                       threshold=ctx.config.anchor_guardian.threshold,
                                       cooldown_sec=ctx.config.anchor_guardian.cooldown_sec))
        if ctx.config.associative_surfacing.enabled:
            from ..subconscious.surfacing import associative_scan
            tasks.append(associative_scan(embedding_f32, ctx,
                                        anchor_threshold=ctx.config.associative_surfacing.anchor_threshold,
                                        session_threshold=ctx.config.associative_surfacing.session_threshold,
                                        max_results=ctx.config.associative_surfacing.max_results))
        if ctx.config.open_loop.enabled:
            from ..subconscious.guardian import scan_open_loops
            tasks.append(scan_open_loops(embedding_f32, ctx,
                                       threshold=ctx.config.open_loop.threshold,
                                       cooldown_sec=ctx.config.open_loop.cooldown_sec,
                                       max_results=ctx.config.open_loop.max_results))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, Exception): continue
            if i == 0 and ctx.config.anchor_guardian.enabled: ctx.conflict_warnings.extend(res)
            elif i == 1 and ctx.config.associative_surfacing.enabled: ctx.surfaced_queue.extend(res)
            elif i == 2 and ctx.config.open_loop.enabled: ctx.open_loops_queue.extend(res)

    # 4. Marker (Step 2)
    source_type = getattr(pctx, 'source_type', SourceType.USER) or SourceType.AGENT
    pctx.mark_result = await _marker(
        text, source_type, session_id, ctx,
        pending_emotions=ctx.pending_emotions,
        embedding=embedding_f32,
    )

    if pctx.mark_result.action == MarkerAction.DISCARD:
        return None

    # Update emotions state
    if pctx.mark_result.action == MarkerAction.CREATE_EMOTION and pctx.mark_result.emotion:
        if pctx.mark_result.emotion.pending:
            ctx.pending_emotions.append(pctx.mark_result.emotion)
    elif pctx.mark_result.action == MarkerAction.CREATE_ENTITY:
        pctx.metadata["resolved_emotions"] = [e for e in ctx.pending_emotions if not e.pending]
        ctx.pending_emotions = [e for e in ctx.pending_emotions if e.pending]

    # Detector signals
    urgency, deadline_val = detect_urgency(text)
    pctx.metadata["urgency"] = urgency
    pctx.metadata["deadline_ts"] = deadline_val
    pctx.metadata["conflict_signal"] = any(w in text.lower() for w in CONFLICT)
    
    pctx.importance = _float_to_importance(
        pctx.mark_result.entity.importance if pctx.mark_result.entity else 0.3
    )

    # 5. Score Step (Step 5)
    await score_step.run(pctx)
    if pctx.should_abort:
        return None

    # 6. Persist Step (Steps 6-8)
    await persist_step.run(pctx)

    # GAP 2/B02: Implicit feedback from LLM response text (feedback_loop_v1.5.md)
    tracker = getattr(ctx, "feedback_tracker", None)
    injected = getattr(ctx, "_last_injected_ids", [])
    if tracker and injected:
        await tracker.on_response(text, injected)
        ctx._last_injected_ids = []

    logger.info(f"Observer processed session {session_id} in {(time.time() - pctx.start_time)*1000:.2f}ms")

    # GAP-9: F-4 — end-to-end pipeline latency across all steps
    _total_ms = round((time.time() - pctx.start_time) * 1000, 2)

    if pctx.sb:
        pctx.sb.entities = pctx.entities
    return pctx.sb
