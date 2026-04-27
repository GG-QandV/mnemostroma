# SPDX-License-Identifier: FSL-1.1-MIT
import time
import logging
from typing import List, Dict, Any, Optional
from ..core import SystemContext
from ..storage.log_writer import log_event

logger = logging.getLogger("mnemostroma.tools.write")

async def save_content(
    content_id: str, 
    text: str, 
    ctx: SystemContext, 
    **kwargs
) -> Any:
    """Save a content block version via ContentManager."""
    if not ctx.content:
        raise RuntimeError("Content branch not initialized")
    
    res = await ctx.content.save(content_id, text, **kwargs)
    
    # Log tool call
    await log_event(ctx, "tools.save_content", "call", {
        "content_id": content_id,
        "text_len": len(text)
    })
    return res

async def ctx_urgent(
    ctx: SystemContext, 
    hours_ahead: float = 72.0
) -> List[Any]:
    """Return all active urgent items within the next N hours."""
    now = time.time()
    cutoff = now + hours_ahead * 3600
    
    results = sorted(
        [i for i in ctx.urgency_index.values()
         if not i.get("expired", False) and (i.get("deadline_ts") or 0) <= cutoff],
        key=lambda x: x.get("deadline_ts") or 9999999999
    )
    
    # Log tool call
    await log_event(ctx, "tools.urgent", "call", {
        "hours_ahead": hours_ahead,
        "found_count": len(results)
    })
    return results

async def ctx_expire(session_id: str, ctx: SystemContext):
    """Explicitly mark a session's urgency as expired."""
    if session_id in ctx.ram_index:
        sb = ctx.ram_index[session_id]
        sb.urgency_expired = True
        # Note: urgency_active logic resides in bridge detection
        
    if session_id in ctx.urgency_index:
        ctx.urgency_index[session_id]["expired"] = True
        
    if ctx.db:
        await ctx.db.execute(
            "UPDATE sessions SET urgency_expired = 1 WHERE session_id = ?",
            (session_id,)
        )
        await ctx.db.commit()
    
    # Log expiration
    await log_event(ctx, "tools.expire", "call", {
        "session_id": session_id
    })
