# SPDX-License-Identifier: FSL-1.1-MIT
import difflib
import hashlib
import time
from dataclasses import dataclass, field

import lz4.frame


@dataclass
class ContentVersion:
    """Single version of a content block."""
    version: int
    content_hash: str
    content_raw: bytes # LZ4 compressed
    content_diff: str | None = None
    content_tags: list[str] = field(default_factory=list)
    tags_verified: bool = False
    why_changed: str | None = None
    status: str = "active" # active/rejected/archived
    embedding: bytes | None = None # float16 512d
    created_at: int = field(default_factory=lambda: int(time.time()))

@dataclass
class ContentBlock:
    """Top-level container for versioned content."""
    content_id: str
    session_id: str
    content_type: str # function/class/chapter/scene/config
    parent_id: str | None = None
    project_id: str | None = None
    status: str = "active"
    versions: list[ContentVersion] = field(default_factory=list)

def compress_content(text: str) -> bytes:
    """Compress text using LZ4 frame format."""
    return lz4.frame.compress(text.encode('utf-8'))

def decompress_content(data: bytes) -> str:
    """Decompress LZ4 frame data back to text."""
    return lz4.frame.decompress(data).decode('utf-8')

def get_content_hash(text: str) -> str:
    """Get SHA256 hash of text."""
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def generate_diff(old_text: str, new_text: str) -> str:
    """Generate unified diff between two versions."""
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile='previous',
        tofile='current'
    )
    return ''.join(diff)
