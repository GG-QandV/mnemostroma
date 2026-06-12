# src/mnemostroma/observer/steps/persist_step.py
# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import TYPE_CHECKING

import numpy as np

from ...memory.session_index import SessionBrief
from ...subconscious.anchor import Anchor
from ...subconscious.anchor_index import AnchorIndex
from ...subconscious.precision_guard import _derive_context_tag, precision_extract
from ...tuner.conflict import tuner_check
from ..continuation_detector import detect_continuation
from ..flag_detector import (
    detect_all_flags,
    detect_mention_type,
    detect_mention_type_embedding,
)
from ..session_classifier import classify_session_type
from ..utils import compress_text
from .base import PipelineContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger("mnemostroma.observer.steps.persist")


def _derive_content_id(entities: list[dict], session_id: str) -> str:
    """Derive a stable content_id from NER entities or fall back to session_id.

    Priority:
        1. NER entity of type 'technology' or 'function' (first found)
        2. NER entity of type 'code' (first found)
        3. Fallback: f"{session_id}_content"
    """
    for ent in entities:
        ent_type = ent.get("type", "")
        if ent_type in ("technology", "function"):
            return re.sub(r"[^a-z0-9_\-]", "_", ent.get("value", "").lower())[:64]
    for ent in entities:
        if ent.get("type") == "code":
            return re.sub(r"[^a-z0-9_\-]", "_", ent.get("value", "").lower())[:64]
    return f"{session_id}_content"


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
            embedding_model_version="multilingual-e5-small",
            content_full=pctx.event.text or None,
            event_role=getattr(pctx.event, "role", None),
        )

        # ── Content Branch routing (Mechanism #12) ──────────────────────────
        _n_classify = getattr(ctx.config, "session_type_classify_after_n", 5)
        _msg_count = pctx.metadata.get("msg_count", 0)
        if _msg_count >= _n_classify:
            pctx.session_type = classify_session_type(stripped)
            pctx.sb.session_type = pctx.session_type

            if pctx.session_type == "content" and getattr(ctx, "content", None) is not None:
                _content_id = _derive_content_id(pctx.entities, session_id)
                _content_tags = [t for t in tags if not t.startswith("org:")]
                try:
                    await ctx.content.save(
                        content_id=_content_id,
                        text=stripped,
                        content_type="text",
                        session_id=session_id,
                        tags=_content_tags,
                        why_changed=pctx.sb.brief,
                    )
                except Exception as _ce:
                    logger.warning("Content branch save failed: %s", _ce)
        # ── End Content Branch routing ───────────────────────────────────────

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
            
            # Polarity Matrix (SPEC §1.3)
            charge = None
            w0 = 1.0
            
            has_neg_emo = False
            has_pos_emo = False
            for e in resolved_emotions:
                val = e.charge.value if hasattr(e.charge, 'value') else str(e.charge)
                if val == "negative": has_neg_emo = True
                if val == "positive": has_pos_emo = True

            if has_neg_emo:
                charge = "negative"
                emo = next(e for e in resolved_emotions if (e.charge.value if hasattr(e.charge, 'value') else str(e.charge)) == "negative")
                w0 = float(getattr(emo, 'intensity', 0.5))
            elif pctx.sb.conflict_flag:
                charge = "negative"
                w0 = 0.7  # W_CONFLICT
            elif has_pos_emo:
                charge = "positive"
                emo = next(e for e in resolved_emotions if (e.charge.value if hasattr(e.charge, 'value') else str(e.charge)) == "positive")
                w0 = float(getattr(emo, 'intensity', 0.5))
            elif not is_new_entity:
                charge = "positive"
                w0 = 0.5  # W_DEEP_USE
            
            if charge and embedding_f32 is not None:
                ctx.experience_index.record_vec(pctx.sb.tags, embedding_f32, charge, w0, ts=created_at)
                if ctx.persistence:
                    cap = ctx.config.experience.evaluator_vecs_cap
                    for tag in pctx.sb.tags:
                        await ctx.persistence.insert_experience_vector(tag, charge, embedding_f32.astype(np.float16).tobytes(), len(embedding_f32), w0, created_at, cap)

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

        # step_log collection (SPEC §4)
        if ctx.config.experience.process_vec_enabled:
            if session_id not in ctx.step_counters:
                if len(ctx.step_logs) >= ctx.config.experience.step_log_sessions_cap:
                    # Use last known ts from last flushed entry; fall back to 0 only if truly empty
                    oldest_sid = min(ctx.step_logs.keys(), key=lambda k: ctx.step_logs[k][-1]["ts"] if ctx.step_logs[k] else ctx.step_counters.get(k, 0))
                    if oldest_sid in ctx.step_logs and ctx.persistence and ctx.step_logs[oldest_sid]:
                        asyncio.create_task(ctx.persistence.insert_session_steps(list(ctx.step_logs[oldest_sid])))
                    ctx.step_logs.pop(oldest_sid, None)
                    ctx.step_counters.pop(oldest_sid, None)
                ctx.step_counters[session_id] = 1
                ctx.step_logs[session_id] = []
            else:
                ctx.step_counters[session_id] += 1
            
            idx = ctx.step_counters[session_id]
            if len(ctx.step_logs[session_id]) < 500:
                ctx.step_logs[session_id].append({
                    "session_id": session_id,
                    "msg_index": idx,
                    "ts": created_at,
                    "importance": pctx.importance,
                    "tags": pctx.sb.tags[:3],  # SPEC §4: max 3 tags per step entry
                    "outcome": detected_flags.get("outcome")
                })
                
                flush_n = ctx.config.experience.process_vec_step_flush_every_n
                if idx % flush_n == 0:
                    if ctx.persistence and ctx.step_logs[session_id]:
                        asyncio.create_task(ctx.persistence.insert_session_steps(list(ctx.step_logs[session_id])))
                    ctx.step_logs[session_id].clear()
            else:
                # cap 500 reached — warn once (first time len == 500), then silently stop
                if len(ctx.step_logs[session_id]) == 500:
                    logger.warning("Session %s hit step_log cap (500 steps). Accumulation stopped.", session_id)


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
