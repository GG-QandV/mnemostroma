# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import time
import json
import logging
from typing import Dict, Any, List, Optional
import numpy as np
from .filter import deterministic_filter
from .embedder import Embedder
from .utils import compress_text
from ..memory.session_index import SessionBrief
from ..core import SystemContext

logger = logging.getLogger("mnemostroma.observer")

from ..memory.scoring import calculate_score, get_importance_weight

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
    
    # 1. Deterministic filter
    filt = deterministic_filter(text)
    
    # Log Filter (v1.0 Point #1)

    if filt["importance"] == "background" and not filt["precision_items"]:
        # Discard irrelevant content
        return None

    # 2. NER (Step 1.5)
    entities = []
    ner_start = time.time()
    if filt["needs_ner"] and ctx.models and ctx.models.ner:
        entities = await ctx.models.ner.extract_entities(
            text, 
            threshold=ctx.config.importance.ner_score_threshold
        )
        
    # Log NER (v1.0 Point #2)

    # 3. Compression
    brief, tags = compress_text(text, entities)
    
    # 4. Vectorization
    vec_start = time.time()
    meta_text = f"{brief} {' '.join(tags)}"
    loop = asyncio.get_event_loop()
    
    if ctx.models and ctx.models.embedder:
        embedding = await loop.run_in_executor(None, ctx.models.embedder.encode, meta_text)
    else:
        # Mock embedding for tests (Deterministic seed for reproducibility)
        np.random.seed(42)
        embedding = np.random.rand(768).astype(np.float16)

    # Log Embed (v1.0 Point #3)

    # 5. Scoring (Profile A: Write)
    score_start = time.time()
    relevance = 0.5
    if intent_vector is not None:
        relevance = float(np.dot(embedding, intent_vector))
        
    created_at = int(time.time())
    
    # Calculate R, T, I components for logging
    I = get_importance_weight(filt["importance"], ctx)
    T = 1.0 # New session
    
    score = await calculate_score(
        relevance, 
        created_at, 
        filt["importance"], 
        ctx, 
        profile="write"
    )

    # Log Score (v1.0 Point #4)

    # 6. Create SessionBrief
    # v1.3: Background with precision = Bare Entity (Precision Log)
    is_bare = (filt["importance"] == "background" and len(filt["precision_items"]) > 0)
    
    sb = SessionBrief(
        session_id=session_id,
        brief=brief,
        tags=tags[:ctx.config.observer.tags_max_per_session],
        importance=filt["importance"],
        score=score,
        resolution=1.0,
        created_at=created_at,
        conflict_flag=filt["conflict"],
        urgency=filt["urgency"],
        deadline_ts=filt["deadline_val"],
        bare_entity=is_bare,
        embedding=embedding,
        embedding_model_version="gte-multilingual-base-int8"
    )

    # 6.5. Pass through Tuner checking for Conflicts
    from ..tuner.conflict import tuner_check
    sb = await tuner_check(sb, ctx)

    # 7. Update RAM and Indices
    ctx.ram_index[session_id] = sb

    # Update Urgency Index (v1.3)
    if sb.urgency != "none" and sb.deadline_ts:
        # Calculate dynamic hours_left (v1.3)
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
        
    if ctx.hnsw_session:
        label = ctx.get_hnsw_label(session_id)
        ctx.hnsw_session.add_items([embedding], [label])
        ctx.id_to_sid[label] = session_id
        ctx.sid_to_id[session_id] = label

    # 8. Async Flush to SQLite
    if hasattr(ctx, 'db_manager') and ctx.db_manager:
        await ctx.db_manager.queue_write(sb)

    # Log Save (v1.0 Point #5)

    latency = (time.time() - start_time) * 1000
    logger.info(f"Observer processed session {session_id} in {latency:.2f}ms")
    
    return sb
