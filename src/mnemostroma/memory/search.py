# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import time
import numpy as np
import logging
from typing import List, Dict, Any, Optional
from ..core import SystemContext
from ..memory.session_index import SessionBrief
from .scoring import calculate_score

logger = logging.getLogger("mnemostroma.memory")

async def semantic_search(
    query: str,
    ctx: SystemContext,
    k: int = 20,
    top_n: int = 5
) -> List[SessionBrief]:
    """Perform hybrid semantic search: KNN -> Query Expansion -> Rerank.
    
    Args:
        query: Search query string.
        ctx: System context.
        k: Number of candidates from KNN.
        top_n: Number of final results after reranking.
        
    Returns:
        List[SessionBrief]: Top-N ranked results.
    """
    if not ctx.session_index or not ctx.models or not ctx.models.embedder:
        return []

    # RuntimeError Fix: Avoid knn_query on empty index
    if ctx.session_index.get_current_count() == 0:
        logger.info("Semantic search: Index is empty, returning no results.")
        return []

    # 1. Vectorize query with model-specific prefix (Config-Driven)
    model_def = ctx.config.manifest.active_models.get("session_embedder")
    prefix = model_def.query_prefix if model_def else ""
    full_query = f"{prefix}{query}" if prefix else query
    
    query_vector = await ctx.models.embedder.aencode(full_query)

    # 2. KNN Search in HNSW — lock prevents race with concurrent add_items
    async with ctx.index_lock:
        labels, distances = ctx.session_index.knn_query(query_vector, k=k)
    
    # Map labels back to session_ids (deduplicate — same sid may have multiple HNSW labels)
    seen_sids: set = set()
    candidates = []
    for label in labels:
        sid = ctx.id_to_sid.get(int(label))
        if sid and sid in ctx.ram_index and sid not in seen_sids:
            seen_sids.add(sid)
            candidates.append(ctx.ram_index[sid])

    if not candidates:
        return []
        
    # 3. Reranking with TinyBERT
    # If no reranker, use distances/relevance directly
    relevances = []
    if ctx.models.reranker:
        loop = asyncio.get_event_loop()
        briefs = [f"{c.brief} {' '.join(c.tags)}" for c in candidates]
        raw = await loop.run_in_executor(
            None, ctx.models.reranker.rerank, query, briefs
        )
        # rerank() returns List[Tuple[str, float]] with raw logits
        # Apply sigmoid to normalize logits → [0, 1] for scoring formula
        relevances = [float(1.0 / (1.0 + np.exp(-score))) for _, score in raw]
    else:
        # Fallback to HNSW distances transformed to relevance (conceptually 1 - dist)
        relevances = [float(1.0 - d) for d in distances]

    # KNN/HNSW Log (Privacy-conscious: no full query text)
    
    final_results = []
    for i, cand in enumerate(candidates):
        rel = relevances[i]
        
        cand.score = await calculate_score(
            rel, 
            cand.created_at, 
            cand.importance, 
            ctx, 
            profile="search",
            urgency_expired=cand.urgency_expired
        )
        final_results.append(cand)
            
    # Sort by final score
    final_results.sort(key=lambda x: x.score, reverse=True)
    
    # Rerank Log
    
    return final_results[:top_n]
