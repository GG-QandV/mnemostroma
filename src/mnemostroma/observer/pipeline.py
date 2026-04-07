# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import time
import logging
from typing import Dict, Any, List, Optional
import numpy as np
from .filter import detect_urgency, CONFLICT
from .marker import marker as _marker, structural_prefilter
from .entities import SourceType, MarkerAction
from .utils import compress_text
from ..memory.session_index import SessionBrief
from ..core import SystemContext

logger = logging.getLogger("mnemostroma.observer")

from ..memory.scoring import calculate_score, get_importance_weight


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
    intent_vector: Optional[np.ndarray] = None
) -> Optional[SessionBrief]:
    """Process agent output through the full Observer pipeline.
    
    Args:
        text: Agent's generated output.
        session_id: Current session identifier.
        ctx: System context with models and indices.
        intent_vector: Optional vector of the current intentional focus.
        
    Returns:
        Optional[SessionBrief]: Created memory object if significant.
    """
    start_time = time.time()
    dim = ctx.config.search.embedding_dim

    # 0. Sync pre-filter — avoids wasting ONNX on guaranteed discards (<1ms)
    stripped = text.strip()
    if len(stripped) < 5 or not structural_prefilter(stripped):
        return None

    # 1. Embed + NER in parallel — before marker() so classification is instant
    #    Both run in separate ThreadPoolExecutors (no GIL, genuine parallelism).
    #    Net latency: max(embed, NER) instead of embed + NER sequentially.
    #    On ≤4-core machines ONNX thread contention may reduce the benefit.
    pipe_start = time.time()

    async def _pre_embed():
        if ctx.models and ctx.models.embedder:
            try:
                raw = await ctx.models.embedder.aencode(stripped)
                return np.array(raw, dtype=np.float32).flatten()
            except Exception as e:
                logger.warning(f"observer: pre-embed failed: {e}")
        return None

    async def _pre_ner():
        if ctx.models and ctx.models.ner:
            try:
                return await ctx.models.ner.extract_entities(
                    text, threshold=ctx.config.importance.ner_score_threshold
                )
            except Exception as e:
                logger.warning(f"observer: pre-ner failed: {e}")
        return []

    pre_embedding, pre_entities = await asyncio.gather(_pre_embed(), _pre_ner())


    # Fallback embedding if pre-embed failed
    embedding: np.ndarray = (
        pre_embedding if pre_embedding is not None
        else np.random.rand(dim).astype(np.float16)
    )

    # 2. Marker — receives pre-computed embedding, skips encode internally
    mark_result = await _marker(
        text, SourceType.AGENT, session_id, ctx,
        pending_emotions=ctx.pending_emotions,  # § 5.2
        embedding=embedding,
    )

    if mark_result.action == MarkerAction.DISCARD:
        return None

    # § 5.2: Update pending_emotions registry based on marker result
    resolved_emotions: list = []
    if mark_result.action == MarkerAction.CREATE_EMOTION and mark_result.emotion:
        if mark_result.emotion.pending:
            ctx.pending_emotions.append(mark_result.emotion)
    elif mark_result.action == MarkerAction.CREATE_ENTITY:
        # resolve_pending_emotions was called inside marker() — capture resolved before clearing
        resolved_emotions = [e for e in ctx.pending_emotions if not e.pending]
        ctx.pending_emotions = [e for e in ctx.pending_emotions if e.pending]

    # Supporting signals not yet in marker: urgency/deadline/conflict keywords
    urgency, deadline_val = detect_urgency(text)
    conflict_signal = any(w in text.lower() for w in CONFLICT)

    importance_str = _float_to_importance(
        mark_result.entity.importance if mark_result.entity else 0.3
    )

    # Log marker result

    # 3. Compression (uses NER entities for tags)
    entities = pre_entities if mark_result.action == MarkerAction.CREATE_ENTITY else []
    brief, tags = compress_text(text, entities)

    # 5. Scoring (Profile A: Write)
    score_start = time.time()
    relevance = 0.5
    if intent_vector is not None:
        relevance = float(np.dot(embedding, intent_vector))
        
    created_at = int(time.time())
    
    # Calculate R, T, I components for logging
    I = get_importance_weight(importance_str, ctx)
    T = 1.0  # New session

    score = await calculate_score(
        relevance,
        created_at,
        importance_str,
        ctx,
        profile="write"
    )

    # Log Score (v1.0 Point #4)

    # 6. Create SessionBrief
    # Bare entity: background-level text that passed marker (no strong signal)
    is_bare = importance_str == "background"

    sb = SessionBrief(
        session_id=session_id,
        brief=brief,
        tags=tags[:ctx.config.observer.tags_max_per_session],
        importance=importance_str,
        score=score,
        resolution=1.0,
        created_at=created_at,
        conflict_flag=conflict_signal,
        urgency=urgency,
        deadline_ts=deadline_val,
        bare_entity=is_bare,
        embedding=embedding,
        embedding_model_version="multilingual-e5-small"
    )

    # 6.5b. Create Anchor (irreducible event skeleton)
    from ..subconscious.anchor import Anchor
    from ..subconscious.anchor_index import AnchorIndex
    from .flag_detector import detect_all_flags

    anchor_type = AnchorIndex.infer_anchor_type(importance_str, entities)
    key_facts = AnchorIndex.build_key_facts(entities, max_facts=5)
    detected_flags = detect_all_flags(text, entities)

    # 6.5 + 7. Continuation + conflict + write
    vec_f32 = embedding.astype(np.float32).flatten()

    from .continuation_detector import detect_continuation
    from ..tuner.conflict import tuner_check

    pipeline_width = ctx.config.search.pipeline_width

    if pipeline_width >= 4:
        # pipeline_width=4: reads in parallel, write atomic under lock
        async def _run_continuation():
            return detect_continuation(
                current_embedding=embedding,
                current_tags=tags,
                ctx=ctx,
                continuation_score_threshold=ctx.config.calibration.continuation_threshold,
            )

        async def _run_conflict():
            try:
                return await tuner_check(sb, ctx)
            except Exception as e:
                logger.error(f"Tuner failed, skipping conflict check: {e}")
                return sb

        cont, sb = await asyncio.gather(_run_continuation(), _run_conflict())

        async with ctx.index_lock:
            if ctx.session_index:
                label = ctx.get_session_label(session_id)
                ctx.session_index.add_items([vec_f32], [label])
                ctx.id_to_sid[label] = session_id
                ctx.sid_to_id[session_id] = label
                if hasattr(ctx, 'calibration') and ctx.calibration:
                    ctx.calibration.record(vec_f32)

    else:
        # pipeline_width=2 (default): sequential, all under lock
        async with ctx.index_lock:
            cont = detect_continuation(
                current_embedding=embedding,
                current_tags=tags,
                ctx=ctx,
                continuation_score_threshold=ctx.config.calibration.continuation_threshold,
            )
            try:
                sb = await tuner_check(sb, ctx)
            except Exception as e:
                logger.error(f"Tuner failed, skipping conflict check: {e}")
            if ctx.session_index:
                label = ctx.get_session_label(session_id)
                ctx.session_index.add_items([vec_f32], [label])
                ctx.id_to_sid[label] = session_id
                ctx.sid_to_id[session_id] = label
                if hasattr(ctx, 'calibration') and ctx.calibration:
                    ctx.calibration.record(vec_f32)

    # Process continuation result (both pipeline paths)
    is_new_entity = True
    continuation_of = None
    continuation_depth = 0
    if cont["state"] in ("continuation", "related"):
        is_new_entity = cont["state"] != "continuation"
        continuation_of = cont["continuation_of"]
        continuation_depth = cont["continuation_depth"]
        if cont["state"] == "continuation" and continuation_of and ctx.anchor_index:
            prev_anchor = ctx.anchor_index.get(continuation_of)
            if prev_anchor:
                prev_anchor.touch()
                ctx.anchor_index.put(prev_anchor)
                if ctx.persistence:
                    await ctx.persistence.save_anchor(prev_anchor)

    # Extract temporal relations from the marker entity (§ 5.1)
    # Source: mark_result.entity — Entity built by marker() with _build_t_rel()
    # pre_entities are raw NER dicts and carry no t_rel field.
    t_rel: dict = {"after": [], "before": [], "caused_by": [], "during": []}
    if mark_result.entity and not mark_result.entity.t_rel.is_empty():
        er = mark_result.entity.t_rel
        t_rel["after"] = list(er.after)
        t_rel["before"] = list(er.before)
        t_rel["caused_by"] = list(er.caused_by)
        t_rel["during"] = list(er.during)

    anchor = Anchor(
        anchor_id=session_id,
        session_id=session_id,
        brief=brief,
        anchor_type=anchor_type,
        key_facts=key_facts,
        flags={
            "is_new_entity": is_new_entity,
            "continuation_of": continuation_of,
            "continuation_depth": continuation_depth,
            "mention_type": detected_flags["mention_type"],
            "outcome": detected_flags["outcome"],
            "user_pin": detected_flags["user_pin"],
            "multi_session": detected_flags["multi_session"] or (continuation_of is not None),
        },
        t_rel=t_rel,
        decay_level=0,
        access_count=0,
        last_accessed_at=created_at,
        created_at=created_at,
        updated_at=created_at,
    )

    if ctx.anchor_index:
        ctx.anchor_index.put(anchor)

    if ctx.persistence:
        await ctx.persistence.save_anchor(anchor)


    # 7b. RAM indices (no HNSW, no lock needed)
    ctx.ram_index[session_id] = sb

    if sb.urgency != "none" and sb.deadline_ts:
        hours_left = (sb.deadline_ts - created_at) / 3600
        ctx.urgency_index[session_id] = {
            "value": sb.brief,
            "session_id": sb.session_id,
            "deadline_ts": sb.deadline_ts,
            "hours_left": round(hours_left, 1),
            "urgency": sb.urgency,
            "importance": sb.importance,
            "tags": sb.tags,
            "expired": sb.urgency_expired
        }

    # 7c. Experience Layer update
    if ctx.experience_index is not None and sb.tags:
        ctx.experience_index.update(
            tags=sb.tags,
            is_continuation=not is_new_entity,
            is_conflict=bool(sb.conflict_flag),
        )
        # § 5.4: Emotional patterns — record resolved emotions against entity tags
        for emo in resolved_emotions:
            charge_val = emo.charge.value if hasattr(emo.charge, 'value') else str(emo.charge)
            intensity = float(getattr(emo, 'intensity', 0.5))
            ctx.experience_index.update_emotion(sb.tags, charge_val, intensity)
        # Persist updated clusters — awaited to guarantee disk write before pipeline exits
        if ctx.persistence:
            for tag in sb.tags:
                cluster = ctx.experience_index.get(tag)
                if cluster:
                    await ctx.persistence.save_experience(
                        tag=cluster.tag,
                        session_count=cluster.session_count,
                        score_sum=cluster.score_sum,
                        conflict_count=cluster.conflict_count,
                        last_updated=cluster.last_updated,
                        emotion_positive=cluster.emotion_positive,
                        emotion_negative=cluster.emotion_negative,
                        emotion_intensity_sum=cluster.emotion_intensity_sum,
                    )

    # 8. Async Flush to SQLite
    if ctx.persistence:
        ctx.persistence.enqueue_session(sb)

    # Log Save (v1.0 Point #5)
    
    latency = (time.time() - start_time) * 1000
    logger.info(f"Observer processed session {session_id} in {latency:.2f}ms")
    
    return sb
