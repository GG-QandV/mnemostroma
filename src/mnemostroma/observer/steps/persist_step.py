# src/mnemostroma/observer/steps/persist_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import time
import logging
import asyncio
import numpy as np
from typing import TYPE_CHECKING
from .base import PipelineContext
from ...memory.session_index import SessionBrief
from ..utils import compress_text
from ...subconscious.anchor import Anchor
from ...subconscious.anchor_index import AnchorIndex
from ..flag_detector import detect_all_flags, detect_mention_type_embedding, detect_mention_type
from ..continuation_detector import detect_continuation
from ...tuner.conflict import tuner_check
from ...subconscious.precision_guard import precision_extract, _derive_context_tag

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mnemostroma.observer.steps.persist")


class PersistStep:
    """Steps 6-8: Create objects, update indices, and enqueue persistence."""

    async def run(self, pctx: PipelineContext) -> PipelineContext:
        ctx = pctx.ctx
        session_id = pctx.event.session_id
        created_at = pctx.metadata.get("created_at", int(time.time()))
        stripped = pctx.metadata.get("stripped", pctx.event.text.strip())
        
        # Conver bytes back to float32 np.ndarray for internal components
        embedding_f32 = pctx.metadata.get("embedding_f32")
        if embedding_f32 is None and pctx.embedding:
            embedding_f32 = np.frombuffer(pctx.embedding, dtype=np.float16).astype(np.float32)

        pctx.importance = pctx.importance or "background"
        is_bare = pctx.importance == "background"
        
        brief, tags = compress_text(pctx.event.text, pctx.entities)
        
        pctx.sb = SessionBrief(
            session_id=session_id,
            brief=brief,
            tags=tags[:ctx.config.observer.tags_max_per_session],
            importance=pctx.importance,
            score=pctx.score or 0.0,
            resolution=1.0,
            created_at=created_at,
            conflict_flag=pctx.metadata.get("conflict_signal", False),
            urgency=pctx.metadata.get("urgency", "none"),
            deadline_ts=pctx.metadata.get("deadline_ts"),
            bare_entity=is_bare,
            embedding=embedding_f32,
            embedding_model_version="multilingual-e5-small"
        )

        # 6.5b. Create Anchor
        anchor_type = AnchorIndex.infer_anchor_type(pctx.importance, pctx.entities)
        key_facts = AnchorIndex.build_key_facts(pctx.entities, max_facts=5)
        detected_flags = detect_all_flags(pctx.event.text, pctx.entities)

        # mention_type logic
        _mt_cfg = getattr(ctx.config, "observer", None)
        _mt_enabled = getattr(_mt_cfg, "mention_type_enabled", True)
        _mt_threshold = getattr(_mt_cfg, "mention_type_threshold", 0.7)
        _embedder = ctx.models.embedder if ctx.models else None
        
        if _mt_enabled and _embedder is not None and embedding_f32 is not None:
            detected_flags["mention_type"] = await detect_mention_type_embedding(
                text_embedding=embedding_f32,
                entities=pctx.entities,
                embedder=_embedder,
                threshold=_mt_threshold,
            )
        else:
            detected_flags["mention_type"] = detect_mention_type(pctx.event.text, pctx.entities)

        # 6.5 + 7. Continuation + conflict + write
        vec_f32 = embedding_f32.astype(np.float32).flatten() if embedding_f32 is not None else _normalized_rand(384)

        pipeline_width = ctx.config.search.pipeline_width

        if pipeline_width >= 4:
            async def _run_continuation():
                return detect_continuation(
                    current_embedding=embedding_f32,
                    current_tags=tags,
                    ctx=ctx,
                    continuation_score_threshold=ctx.config.calibration.continuation_threshold,
                )

            async def _run_conflict():
                try:
                    return await tuner_check(pctx.sb, ctx)
                except Exception as e:
                    logger.error(f"Tuner failed, skipping conflict check: {e}")
                    return pctx.sb

            cont, pctx.sb = await asyncio.gather(_run_continuation(), _run_conflict())

            async with ctx.index_lock:
                if ctx.session_index:
                    label = ctx.get_session_label(session_id)
                    ctx.session_index.add_items([vec_f32], [label])
                    ctx.id_to_sid[label] = session_id
                    ctx.sid_to_id[session_id] = label
        else:
            async with ctx.index_lock:
                cont = detect_continuation(
                    current_embedding=embedding_f32,
                    current_tags=tags,
                    ctx=ctx,
                    continuation_score_threshold=ctx.config.calibration.continuation_threshold,
                )
                try:
                    pctx.sb = await tuner_check(pctx.sb, ctx)
                except Exception as e:
                    logger.error(f"Tuner failed, skipping conflict check: {e}")
                if ctx.session_index:
                    label = ctx.get_session_label(session_id)
                    ctx.session_index.add_items([vec_f32], [label])
                    ctx.id_to_sid[label] = session_id
                    ctx.sid_to_id[session_id] = label

        # Process continuation result
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

        # Temporal relations
        t_rel: dict = {"after": [], "before": [], "caused_by": [], "during": []}
        if pctx.mark_result and pctx.mark_result.entity and not pctx.mark_result.entity.t_rel.is_empty():
            er = pctx.mark_result.entity.t_rel
            t_rel["after"] = list(er.after)
            t_rel["before"] = list(er.before)
            t_rel["caused_by"] = list(er.caused_by)
            t_rel["during"] = list(er.during)

        # Normalize anchor embedding
        _emb_norm = np.linalg.norm(embedding_f32) if embedding_f32 is not None else 0
        _anchor_embedding = (embedding_f32 / _emb_norm) if _emb_norm > 1e-9 else embedding_f32

        pctx.anchor = Anchor(
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
            embedding=_anchor_embedding,
        )

        if ctx.anchor_index is not None:
            ctx.anchor_index.put(pctx.anchor)

        if ctx.persistence is not None:
            await ctx.persistence.save_anchor(pctx.anchor)


        # 7b. RAM indices
        ctx.ram_index[session_id] = pctx.sb

        if pctx.sb.urgency != "none" and pctx.sb.deadline_ts:
            hours_left = (pctx.sb.deadline_ts - created_at) / 3600
            ctx.urgency_index[session_id] = {
                "value": pctx.sb.brief,
                "session_id": pctx.sb.session_id,
                "deadline_ts": pctx.sb.deadline_ts,
                "hours_left": round(hours_left, 1),
                "urgency": pctx.sb.urgency,
                "importance": pctx.sb.importance,
                "tags": pctx.sb.tags,
                "expired": pctx.sb.urgency_expired
            }

        # 7c. Experience Layer update
        if ctx.experience_index is not None and pctx.sb.tags:
            # S-3: snapshot maturity levels BEFORE update to detect transitions
            _old_maturities: dict = {}
            for _tag in pctx.sb.tags:
                _cl = ctx.experience_index.get(_tag)
                if _cl is not None:
                    _old_maturities[_tag] = _cl.maturity

            ctx.experience_index.update(
                tags=pctx.sb.tags,
                is_continuation=not is_new_entity,
                is_conflict=bool(pctx.sb.conflict_flag),
            )

            # S-3: log maturity transitions (novice→apprentice→practitioner→expert→master)
            for _tag in pctx.sb.tags:
                _cl = ctx.experience_index.get(_tag)
                if _cl is None:
                    continue
                _new_mat = _cl.maturity
                _old_mat = _old_maturities.get(_tag)
                if _old_mat is not None and _old_mat != _new_mat:
                    pass

            resolved_emotions = pctx.metadata.get("resolved_emotions", [])
            for emo in resolved_emotions:
                charge_val = emo.charge.value if hasattr(emo.charge, 'value') else str(emo.charge)
                intensity = float(getattr(emo, 'intensity', 0.5))
                ctx.experience_index.update_emotion(pctx.sb.tags, charge_val, intensity)
            
            if ctx.persistence:
                for tag in pctx.sb.tags:
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

        # 8.5. Precision RAM update
        if ctx.config.precision_guard.enabled:
            _prec_now = int(time.time())
            _prec_items = []
            for _artifact in precision_extract(stripped):
                _ctx_tag = _derive_context_tag(_artifact, stripped)
                _key = (_artifact["type"], _ctx_tag)
                ctx.precision_ram[_key] = {
                    "value": _artifact["value"],
                    "session_id": session_id,
                    "stored_at": _prec_now,
                }
                _prec_items.append({
                    "id": f"{session_id}_{_artifact['type']}_{_ctx_tag}",
                    "type": _artifact["type"],
                    "value": _artifact["value"],
                    "context_tag": _ctx_tag,
                })
            while len(ctx.precision_ram) > ctx.config.precision_guard.ram_cap:
                _oldest = min(ctx.precision_ram, key=lambda k: ctx.precision_ram[k].get("stored_at", 0))
                del ctx.precision_ram[_oldest]
            if _prec_items:
                pctx.sb.precision_items = _prec_items

        # 8. Async Flush to SQLite (enqueue)
        if ctx.persistence:
            ctx.persistence.enqueue_session(pctx.sb)

        # Log Save
        
        return pctx

def _normalized_rand(dim: int) -> np.ndarray:
    """Normalized random fallback vector."""
    v = np.random.rand(dim).astype(np.float32)
    return v / np.linalg.norm(v)
