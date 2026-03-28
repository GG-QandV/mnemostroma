# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import time
import numpy as np
from typing import List, Dict, Any, Optional
from ..core import SystemContext
from ..memory.session_index import SessionBrief
from .scoring import calculate_score

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
    if not ctx.hnsw_session or not ctx.models or not ctx.models.embedder:
        return []

    # 1. Vectorize query
    loop = asyncio.get_event_loop()
    query_vector = await loop.run_in_executor(None, ctx.models.embedder.encode, query)

    # 2. KNN Search in HNSW
    labels, distances = ctx.hnsw_session.knn_query(query_vector, k=k)
    
    # Map labels back to session_ids
    candidates = []
    for label in labels[0]: # labels is 2D array [1, k]
        sid = ctx.id_to_sid.get(int(label))
        if sid and sid in ctx.ram_index:
            candidates.append(ctx.ram_index[sid])
    
    if not candidates:
        return []

    # 3. Reranking with TinyBERT
    # If no reranker, use distances/relevance directly
    relevances = []
    if ctx.models.reranker:
        briefs = [f"{c.brief} {' '.join(c.tags)}" for c in candidates]
        relevances = await loop.run_in_executor(
            None, ctx.models.reranker.rank, query, briefs
        )
    else:
        # Fallback to HNSW distances transformed to relevance (conceptually 1 - dist)
        relevances = [float(1.0 - d) for d in distances[0]]

    # KNN/HNSW Log (immediate, before scoring)

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
