# SPDX-License-Identifier: FSL-1.1-MIT
import time
import logging
from typing import List, Dict, Any, Optional
from ..core import SystemContext
from ..memory.search import semantic_search
from ..feedback.implicit import signal_use, ImplicitFeedbackTracker

logger = logging.getLogger("mnemostroma.tools.read")

async def ctx_get(session_id: str, ctx: SystemContext) -> Optional[Any]:
    """Retrieve session from RAM or lazy load from SQLite.

    Emits a USE signal via implicit feedback on successful retrieval.

    Args:
        session_id: Unique session identifier.
        ctx: System context.

    Returns:
        Optional[SessionBrief]: The session object if found.
    """
    if session_id in ctx.ram_index:
        sb = ctx.ram_index[session_id]
        # Emit USE signal — agent explicitly requested this session
        await signal_use(session_id, ctx)
        return sb

    # Lazy load from SQLite
    if ctx.db:
        from ..storage.lazy_loader import lazy_load_session
        sb = await lazy_load_session(session_id, ctx.db)
        if sb:
            ctx.ram_index[session_id] = sb
            label = ctx.get_session_label(session_id)
            ctx.sid_to_id[session_id] = label
            ctx.id_to_sid[label] = session_id
            await signal_use(session_id, ctx)
            return sb

    return None

async def ctx_semantic(
    query: str, 
    ctx: SystemContext, 
    k: int = 20, 
    top_n: int = 5
) -> List[Any]:
    """Perform high-precision semantic search.

    Feeds returned session IDs into ImplicitFeedbackTracker for IGNORE
    detection (rapid re-query < 5s) and deferred USE signals.

    Args:
        query: Search query string.
        ctx: System context.
        k: Candidates limit for ANN.
        top_n: Final results after reranking.
    """
    start = time.time()
    results = await semantic_search(query, ctx, k=k, top_n=top_n)
    latency = (time.time() - start) * 1000

    # B02: Emit IGNORE/USE signals via tracker (feedback_loop_v1.5.md § 4)
    tracker = getattr(ctx, "feedback_tracker", None)
    if tracker:
        returned_ids = [sb.session_id for sb in results]
        await tracker.on_semantic_query(returned_ids)

    # Log tool call (v1.0 spec Point #13)

    return results

async def ctx_search(
    tags: List[str],
    ctx: SystemContext,
    importance: Optional[str] = None,
    age: Optional[str] = None,
    limit: int = 10,
) -> List[Any]:
    """Filter RAM index by tag intersection. Pure RAM, no ONNX (<0.01ms).

    Args:
        tags: List of tags to match (intersection — session must have ALL tags).
        importance: Optional filter: 'critical' | 'important' | 'background' | 'principle'.
        age: Optional filter on age_signal field.
        limit: Max results, sorted by score desc.
    """
    tag_set = set(tags)
    results = [
        sb for sb in ctx.ram_index.values()
        if tag_set.issubset(set(sb.tags))
        and (importance is None or sb.importance == importance)
        and (age is None or sb.age_signal == age)
    ]
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]


async def ctx_full(session_id: str, ctx: SystemContext) -> Optional[Dict[str, Any]]:
    """Load full session record from SQLite including content_full.

    Use only when exact wording is needed — hits SQLite (~0.5ms).
    Emits USE signal on retrieval.
    """
    if ctx.db is None:
        return None
    try:
        async with ctx.db.execute(
            """SELECT session_id, brief, why_log, content_full, tags,
                      importance, created_at, conflict
               FROM sessions WHERE session_id = ?""",
            (session_id,)
        ) as cursor:
            row = await cursor.fetchone()
    except Exception as e:
        logger.error(f"ctx_full: db error for {session_id}: {e}")
        return None

    if row is None:
        return None

    import json as _json
    try:
        tags_val = _json.loads(row[4]) if row[4] else []
    except Exception:
        tags_val = []

    await signal_use(session_id, ctx)
    return {
        "session_id": row[0],
        "brief": row[1],
        "why_log": row[2],
        "content_full": row[3],
        "tags": tags_val,
        "importance": row[5],
        "created_at": row[6],
        "conflict": bool(row[7]),
    }


async def ctx_anchors(
    ctx: SystemContext,
    anchor_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Read anchors from RAM index (subconscious layer).

    Returns full anchor objects without embedding blobs.
    """
    anchor_index = getattr(ctx, "anchor_index", None)
    if anchor_index is None:
        return []

    if anchor_type:
        anchors = anchor_index.query_by_type(anchor_type)
    else:
        anchors = anchor_index.all()

    if session_id:
        anchors = [a for a in anchors if a.session_id == session_id]

    anchors.sort(key=lambda a: a.last_accessed_at, reverse=True)

    result = []
    for a in anchors[:limit]:
        result.append({
            "anchor_id": a.anchor_id,
            "session_id": a.session_id,
            "anchor_type": a.anchor_type,
            "brief": a.brief,
            "key_facts": a.key_facts,
            "flags": a.flags,
            "decay_level": a.decay_level,
            "access_count": a.access_count,
            "last_accessed_at": a.last_accessed_at,
            "t_rel": a.t_rel,
            "created_at": a.created_at,
        })

    return result


async def ctx_precision(
    ctx: SystemContext,
    precision_type: Optional[str] = None,
    importance: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """Read precision artifacts from SQLite precision_log table.

    Types: link / concept / quote / formula / data.
    Small table — fast even with SQLite.
    """
    if ctx.db is None:
        return []

    conditions = []
    params: List[Any] = []
    if precision_type:
        conditions.append("type = ?")
        params.append(precision_type)
    if importance:
        conditions.append("importance = ?")
        params.append(importance)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    try:
        async with ctx.db.execute(
            f"""SELECT precision_id, session_id, type, value, context_tag, importance, created_at
                FROM precision_log {where} ORDER BY created_at DESC LIMIT ?""",
            params
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"ctx_precision: db error: {e}")
        return []

    result = [
        {
            "precision_id": r[0],
            "session_id": r[1],
            "type": r[2],
            "value": r[3],
            "context_tag": r[4],
            "importance": r[5],
            "created_at": r[6],
        }
        for r in rows
    ]
    return result


async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    """Return the current active context summary (bridge) for the agent.
    
    Includes active_variables and urgency_active (v1.3).
    """
    # 1. Intent Summary (Dynamic)
    # Pull from most recent session in RAM or default
    sessions = sorted(ctx.ram_index.values(), key=lambda x: x.created_at, reverse=True)
    intent_summary = sessions[0].brief if sessions else "No active sessions."
    
    # 2. Urgency Active
    urgency_active = sorted(
        [item for item in ctx.urgency_index.values() if not item.get("expired", False)],
        key=lambda x: x.get("deadline_ts", 0) or 9999999999
    )
    
    # 3. Active Variables (Critical/Principle)
    active_vars = [
        f"{k}: {v.brief}" for k, v in ctx.ram_index.items() 
        if v.importance in ("critical", "principle")
    ][:9]
    
    res = {
        "intent_summary": intent_summary,
        "active_variables": active_vars,
        "urgency_active": urgency_active
    }
    
    # Log tool call (v1.0 spec)
    
    return res
