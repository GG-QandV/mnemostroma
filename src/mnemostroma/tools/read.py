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
            label = ctx.get_hnsw_label(session_id)
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
