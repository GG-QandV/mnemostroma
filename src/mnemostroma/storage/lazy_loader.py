# SPDX-License-Identifier: FSL-1.1-MIT
import json
import logging

import aiosqlite
import numpy as np

from ..memory.session_index import SessionBrief

logger = logging.getLogger("mnemostroma.lazy_loader")

async def lazy_load_session(session_id: str, db: aiosqlite.Connection) -> SessionBrief | None:
    """Load a session from SQLite and convert it to a SessionBrief.
    
    Args:
        session_id: Unique session identifier.
        db: SQLite connection.
        
    Returns:
        Optional[SessionBrief]: The restored session brief.
    """
    async with db.execute(
        "SELECT created_at, importance, tags, brief, conflict, embedding FROM sessions WHERE session_id = ?",
        (session_id,)
    ) as cursor:
        row = await cursor.fetchone()
        if not row:
            return None
            
        created_at, importance, tags_json, brief, conflict_int, embed_bytes = row
        
        embedding = None
        if embed_bytes:
            embedding = np.frombuffer(embed_bytes, dtype=np.float16)

        return SessionBrief(
            session_id=session_id,
            created_at=created_at,
            importance=importance,
            tags=json.loads(tags_json),
            brief=brief,
            conflict_flag=bool(conflict_int),
            score=0.5, # Default score until next consolidation
            resolution=1.0,
            embedding=embedding,
            layer="RAM_WARM" # Mark as restored from cold storage
        )
