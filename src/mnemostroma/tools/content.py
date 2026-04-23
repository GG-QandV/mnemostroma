# SPDX-License-Identifier: FSL-1.1-MIT
"""Content branch tools — semantic search, retrieval, versioning.

All content tools return full entity metadata so the agent can decide
what to inspect further (raw text, history, diff). No snippets, no RAG.
"""
import json
import logging
from typing import Any, Dict, List, Optional

import numpy as np

from ..core import SystemContext
from ..storage.content import decompress_content

logger = logging.getLogger("mnemostroma.tools.content")


async def content_search(
    query: str,
    ctx: SystemContext,
    project_id: Optional[str] = None,
    status: str = "active",
    top_k: int = 5,
) -> List[Dict[str, Any]]:
    """Semantic search over content blocks using MatrixSearch + content_embedder.

    Returns full ContentBlock metadata (no raw text). Agent requests content_raw
    explicitly when exact wording is needed.

    Args:
        query: Natural-language description of content to find.
        project_id: Optional filter by project.
        status: 'active' | 'archived' | 'all'.
        top_k: Number of results.
    """
    if ctx.content_index is None or ctx.content_index.get_current_count() == 0:
        return []

    # Encode with content_embedder; fall back to session_embedder
    embedder = None
    if ctx.models:
        embedder = getattr(ctx.models, "content_embedder", None) or getattr(ctx.models, "embedder", None)
    if embedder is None:
        return []

    try:
        raw = await embedder.aencode(query)
        query_vec = np.array(raw, dtype=np.float32).flatten()
    except Exception as e:
        logger.warning(f"content_search: encode failed: {e}")
        return []

    async with ctx.index_lock:
        labels, _ = ctx.content_index.knn_query(query_vec, k=min(top_k * 4, 50))

    # Resolve labels → content_id keys
    content_ids_seen = set()
    candidates = []
    for label in labels:
        key = ctx.id_to_cid.get(int(label))
        if not key:
            continue
        # key format: "content_id_version"
        parts = key.rsplit("_", 1)
        content_id = parts[0] if len(parts) == 2 else key
        if content_id not in content_ids_seen:
            content_ids_seen.add(content_id)
            candidates.append(content_id)

    if not candidates or ctx.db is None:
        return []

    # Fetch metadata from SQLite
    placeholders = ",".join("?" * len(candidates))
    status_filter = "" if status == "all" else f"AND cv.status = '{status}'"
    if project_id:
        proj_filter = f"AND cb.project_id = ?"
        params = candidates + [project_id]
    else:
        proj_filter = ""
        params = candidates

    try:
        async with ctx.db.execute(
            f"""SELECT cb.content_id, cb.content_type, cb.session_id, cb.project_id,
                       cb.status, cv.version, cv.content_tags, cv.why_changed,
                       cv.status AS v_status, cv.created_at
                FROM content_blocks cb
                JOIN content_versions cv ON cb.content_id = cv.content_id
                WHERE cb.content_id IN ({placeholders}) {proj_filter}
                  {status_filter}
                ORDER BY cv.version DESC""",
            params
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"content_search: db error: {e}")
        return []

    # Deduplicate — keep latest version per content_id
    seen: set = set()
    results = []
    for row in rows:
        cid = row[0]
        if cid in seen:
            continue
        seen.add(cid)
        try:
            tags = json.loads(row[6]) if row[6] else []
        except Exception:
            tags = []
        results.append({
            "content_id": cid,
            "content_type": row[1],
            "session_id": row[2],
            "project_id": row[3],
            "block_status": row[4],
            "version": row[5],
            "content_tags": tags,
            "why_changed": row[7],
            "version_status": row[8],
            "created_at": row[9],
        })
        if len(results) >= top_k:
            break

    return results


async def content_get(
    content_id: str,
    ctx: SystemContext,
    version: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """Get ContentBlock metadata. version=None → latest active version.

    Returns metadata only (no raw text). Use content_raw for exact content.
    """
    # Try RAM first
    content_mgr = getattr(ctx, "content", None)
    if content_mgr and content_id in content_mgr.blocks:
        block = content_mgr.blocks[content_id]
        if block.versions:
            if version is not None:
                v = next((v_ for v_ in block.versions if v_.version == version), None)
            else:
                v = next(
                    (v_ for v_ in reversed(block.versions) if v_.status == "active"),
                    block.versions[-1]
                )
            if v:
                return {
                    "content_id": block.content_id,
                    "content_type": block.content_type,
                    "session_id": block.session_id,
                    "project_id": block.project_id,
                    "block_status": block.status,
                    "version": v.version,
                    "content_tags": v.content_tags,
                    "why_changed": v.why_changed,
                    "version_status": v.status,
                    "content_hash": v.content_hash,
                    "created_at": v.created_at,
                }

    if ctx.db is None:
        return None

    version_filter = "AND cv.version = ?" if version is not None else "AND cv.status = 'active'"
    params = [content_id]
    if version is not None:
        params.append(version)

    try:
        async with ctx.db.execute(
            f"""SELECT cb.content_id, cb.content_type, cb.session_id, cb.project_id,
                       cb.status, cv.version, cv.content_tags, cv.why_changed,
                       cv.status, cv.content_hash, cv.created_at
                FROM content_blocks cb
                JOIN content_versions cv ON cb.content_id = cv.content_id
                WHERE cb.content_id = ? {version_filter}
                ORDER BY cv.version DESC LIMIT 1""",
            params
        ) as cursor:
            row = await cursor.fetchone()
    except Exception as e:
        logger.error(f"content_get: db error: {e}")
        return None

    if row is None:
        return None

    try:
        tags = json.loads(row[6]) if row[6] else []
    except Exception:
        tags = []

    return {
        "content_id": row[0],
        "content_type": row[1],
        "session_id": row[2],
        "project_id": row[3],
        "block_status": row[4],
        "version": row[5],
        "content_tags": tags,
        "why_changed": row[7],
        "version_status": row[8],
        "content_hash": row[9],
        "created_at": row[10],
    }


async def content_raw(
    content_id: str,
    ctx: SystemContext,
    version: Optional[int] = None,
) -> Optional[str]:
    """Decompress and return raw content text from SQLite.

    version=None → latest active version. Expensive — use only when
    exact text is needed.
    """
    # Try RAM first
    content_mgr = getattr(ctx, "content", None)
    if content_mgr and content_id in content_mgr.blocks:
        block = content_mgr.blocks[content_id]
        if block.versions:
            if version is not None:
                v = next((v_ for v_ in block.versions if v_.version == version), None)
            else:
                v = next(
                    (v_ for v_ in reversed(block.versions) if v_.status == "active"),
                    block.versions[-1]
                )
            if v and v.content_raw:
                return decompress_content(v.content_raw)

    if ctx.db is None:
        return None

    version_filter = "AND version = ?" if version is not None else "AND status = 'active'"
    params = [content_id]
    if version is not None:
        params.append(version)

    try:
        async with ctx.db.execute(
            f"""SELECT content_raw FROM content_versions
                WHERE content_id = ? {version_filter}
                ORDER BY version DESC LIMIT 1""",
            params
        ) as cursor:
            row = await cursor.fetchone()
    except Exception as e:
        logger.error(f"content_raw: db error: {e}")
        return None

    if row is None or row[0] is None:
        return None

    return decompress_content(row[0])


async def content_history(
    content_id: str,
    ctx: SystemContext,
) -> List[Dict[str, Any]]:
    """List all versions of a content block — metadata only, no raw text.

    Includes rejected versions so the agent can understand why past
    attempts were discarded.
    """
    if ctx.db is None:
        return []

    try:
        async with ctx.db.execute(
            """SELECT version, content_hash, content_tags, why_changed,
                      status, rejected_reason, created_at
               FROM content_versions WHERE content_id = ?
               ORDER BY version ASC""",
            (content_id,)
        ) as cursor:
            rows = await cursor.fetchall()
    except Exception as e:
        logger.error(f"content_history: db error: {e}")
        return []

    result = []
    for row in rows:
        try:
            tags = json.loads(row[2]) if row[2] else []
        except Exception:
            tags = []
        result.append({
            "version": row[0],
            "content_hash": row[1],
            "content_tags": tags,
            "why_changed": row[3],
            "status": row[4],
            "rejected_reason": row[5],
            "created_at": row[6],
        })

    return result
