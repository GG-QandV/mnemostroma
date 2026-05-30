# SPDX-License-Identifier: FSL-1.1-MIT
import logging
import time

import numpy as np

from ..core import SystemContext
from .content import (
    ContentBlock,
    ContentVersion,
    compress_content,
    decompress_content,
    generate_diff,
    get_content_hash,
)

logger = logging.getLogger("mnemostroma.content")

class ContentManager:
    """Manager for Agent Content branch.
    
    Handles versioned storage, search, and retrieval of code/text blocks.
    """
    def __init__(self, ctx: SystemContext):
        self.ctx = ctx
        self.blocks: dict[str, ContentBlock] = {} # RAM cache of active blocks

    async def save(
        self, 
        content_id: str, 
        text: str, 
        content_type: str,
        session_id: str,
        tags: list[str] = None,
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
        from ..models.embedding_utils import aencode_chunks, chunk_content
        chunks = chunk_content(text, content_type)
        
        if self.ctx.models and self.ctx.models.content_embedder:
            embedding = await aencode_chunks(self.ctx.models.content_embedder, chunks)
        else:
            dim = 768
            embedding = np.zeros(dim, dtype=np.float16)

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
        
        # 6. Persistence (Async Flush via PersistenceLayer)
        if self.ctx.persistence:
            self.ctx.persistence.enqueue_session({
                "type": "content_block",
                "content_id": content_id,
                "session_id": session_id,
                "content_type": content_type,
                "status": block.status
            })
            self.ctx.persistence.enqueue_session({
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
            logger.warning("No persistence layer in context, content persistence skipped.")


        # 7. Update content index
        if self.ctx.content_index:
            key = f"{content_id}_{v_num}"
            label = self.ctx.get_content_label(key)
            self.ctx.id_to_cid[label] = key
            self.ctx.cid_to_id[key] = label
            self.ctx.content_index.add_items(
                [embedding.astype('float32')], [label]
            )

        latency = (time.time() - start_time) * 1000
        logger.info(f"Content {content_id} v{v_num} saved in {latency:.2f}ms")
        
        return new_v
