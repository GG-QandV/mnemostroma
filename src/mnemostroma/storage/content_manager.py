# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import json
import logging
import time
import numpy as np
from typing import List, Optional, Dict, Any
from .content import ContentBlock, ContentVersion, compress_content, decompress_content, get_content_hash, generate_diff
from ..core import SystemContext

logger = logging.getLogger("mnemostroma.content")

class ContentManager:
    """Manager for Agent Content branch.
    
    Handles versioned storage, search, and retrieval of code/text blocks.
    """
    def __init__(self, ctx: SystemContext):
        self.ctx = ctx
        self.blocks: Dict[str, ContentBlock] = {} # RAM cache of active blocks

    async def save(
        self, 
        content_id: str, 
        text: str, 
        content_type: str,
        session_id: str,
        tags: List[str] = None,
        why_changed: str = None
    ) -> ContentVersion:
        """Save a new version of a content block.
        
        Args:
            content_id: Unique identifier for the block (e.g. function name).
            text: Raw content.
            content_type: code/text/chapter etc.
            session_id: Current session.
            tags: Semantic tags for the content.
            why_changed: Description of changes.
            
        Returns:
            ContentVersion: The newly created version.
        """
        start_time = time.time()
        
        # 1. Hashing and deduplication
        new_hash = get_content_hash(text)
        
        # Check if block exists in cache or DB
        block = self.blocks.get(content_id)
        if not block:
            # Try to load from DB (stub for lazy load)
            block = ContentBlock(content_id=content_id, session_id=session_id, content_type=content_type)
            self.blocks[content_id] = block

        # Check if hash changed
        last_version = block.versions[-1] if block.versions else None
        if last_version and last_version.content_hash == new_hash:
            logger.info(f"Content {content_id} unchanged, skipping save.")
            return last_version

        # 2. Vectorization (BGE-M3)
        from ..memory.content_embedder import chunk_content
        chunks = chunk_content(text, content_type)
        
        loop = asyncio.get_event_loop()
        if self.ctx.models and self.ctx.models.content_embedder:
            embedding = await loop.run_in_executor(
                None, self.ctx.models.content_embedder.encode_chunks, chunks
            )
        else:
            embedding = np.random.rand(512).astype(np.float16)

        # 3. Diffing
        diff = ""
        if last_version:
            old_text = decompress_content(last_version.content_raw)
            diff = generate_diff(old_text, text)

        # 4. Compression
        compressed = compress_content(text)
        
        # 5. Create Version
        v_num = (last_version.version + 1) if last_version else 1
        new_v = ContentVersion(
            version=v_num,
            content_hash=new_hash,
            content_raw=compressed,
            content_diff=diff,
            content_tags=tags or [],
            why_changed=why_changed,
            embedding=embedding.tobytes()
        )
        
        block.versions.append(new_v)
        
        # 6. Persistence (Async Flush via DatabaseManager)
        if self.ctx.db_manager:
            await self.ctx.db_manager.queue_write({
                "type": "content_block",
                "content_id": content_id,
                "session_id": session_id,
                "content_type": content_type,
                "status": block.status
            })
            await self.ctx.db_manager.queue_write({
                "type": "content_version",
                "content_id": content_id,
                "version": v_num,
                "content_hash": new_hash,
                "content_raw": compressed,
                "content_diff": diff,
                "content_tags": tags or [],
                "why_changed": why_changed,
                "embedding": embedding.tobytes(),
                "created_at": new_v.created_at
            })
        else:
            # Fallback for minimal bootstrap/tests
            logger.warning("No db_manager in context, content persistence skipped.")


        # 7. Update HNSW Index
        if self.ctx.hnsw_content:
            label = hash(f"{content_id}_{v_num}") & 0x7FFFFFFF
            self.ctx.hnsw_content.add_items([embedding], [label])

        latency = (time.time() - start_time) * 1000
        logger.info(f"Content {content_id} v{v_num} saved in {latency:.2f}ms")
        
        return new_v
