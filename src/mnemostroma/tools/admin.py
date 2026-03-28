# SPDX-License-Identifier: FSL-1.1-MIT
"""Administrative tools for Mnemostroma system monitoring and maintenance."""
import time
import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from ..core import SystemContext

logger = logging.getLogger("mnemostroma.tools.admin")

async def ctx_status(ctx: SystemContext) -> Dict[str, Any]:
    """Retrieve current system status and resource metrics.
    
    Returns:
        Dict containing counts for RAM index, HNSW vectors, and DB info.
    """
    stats = {
        "timestamp": time.time(),
        "ram_index_count": len(ctx.ram_index),
        "urgency_count": len(ctx.urgency_index),
        "hnsw_session": {
            "count": ctx.hnsw_session.get_current_count() if ctx.hnsw_session else 0,
            "max_elements": ctx.hnsw_session.get_max_elements() if ctx.hnsw_session else 0,
        },
        "hnsw_content": {
            "count": ctx.hnsw_content.get_current_count() if ctx.hnsw_content else 0,
        },
        "metrics": ctx.metrics
    }
    
    # Log the status check

    return stats

async def ctx_sync(ctx: SystemContext) -> bool:
    """Force flush all pending updates to SQLite and HNSW persistence.
    
    Ensures that high-priority decisions are committed to disk immediately.
    """
    start = time.time()
    try:
        if hasattr(ctx, "db_manager") and ctx.db_manager:
            # Force processing of any pending session writes
            # Note: in a real implementation this might wait for the queue to empty
            await ctx.db_manager.flush()
        
        # HNSW persistence (if configured)
        if ctx.hnsw_content and hasattr(ctx.config, "hnsw_content"):
            content_path = getattr(ctx.config.hnsw_content, "index_path", "content.bin")
            ctx.hnsw_content.save_index(content_path)
            
        latency = (time.time() - start) * 1000

        return True
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return False

async def ctx_dump(ctx: SystemContext, target_dir: Optional[str] = None) -> str:
    """Dump the entire Hot/Warm layer state to a JSON file for debugging.
    
    Args:
        target_dir: Directory to save the dump. Defaults to user home .mnemostroma/dumps.
    """
    if not target_dir:
        target_dir = str(Path.home() / ".mnemostroma" / "dumps")
        
    os.makedirs(target_dir, exist_ok=True)
    filename = f"dump_{int(time.time())}.json"
    filepath = os.path.join(target_dir, filename)
    
    # Extract serializable data
    dump_data = {
        "metadata": {
            "timestamp": time.time(),
            "version": "1.5",
        },
        "ram_index": {
            sid: {
                "brief": sb.brief,
                "importance": sb.importance,
                "created_at": sb.created_at,
                "tags": sb.tags,
                "conflict_flag": sb.conflict_flag
            } for sid, sb in ctx.ram_index.items()
        },
        "urgency": ctx.urgency_index,
        "metrics": ctx.metrics
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=4, ensure_ascii=False)

    return filepath
