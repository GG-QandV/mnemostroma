# SPDX-License-Identifier: FSL-1.1-MIT
from dataclasses import dataclass, field

import numpy as np


@dataclass
class RawObservation:
    """Raw MITM proxy observation queued for async SQLite write.

    Created by mnemo_mitm_proxy._observe() via dispatch("observe_raw", ...),
    queued via DatabaseManager.queue_write(), and flushed to the
    raw_observations table by the single-writer worker task — never
    on the caller's event loop.
    """
    session_id: str
    role: str
    text: str


@dataclass
class SessionBrief:
    """Single session in RAM memory index.
    
    Represents the compressed form of one agent session: brief summary,
    tags, importance level, Score, and dissolution resolution.
    
    Attributes:
        session_id: Unique session identifier.
        brief: Compressed summary, max 50 chars.
        tags: Semantic tags extracted by Observer, max 7.
        importance: Level: background/important/critical/principle.
        score: Ranking score = α×R + β×T + γ×I.
        resolution: Dissolution level 0.05–1.0, managed by Dissolver.
        created_at: Creation timestamp (UTC).
        use_count: Frequency of retrieval in active context.
        conflict_flag: Indicates semantic dissonance with other sessions.
        urgency: Level: none/deadline_h/deadline_d/deadline_w.
        deadline_ts: Optional deadline timestamp.
        urgency_active: Whether urgency policy is currently applied.
        urgency_expired: Whether the deadline has passed.
        layer: Current memory layer: RAM_HOT, RAM_WARM, etc.
        embedding: Vector representation (512d MRL).
        implicit_score: Feedback-driven quality score (0.0-1.0).
    """
    session_id: str
    brief: str
    tags: list[str]
    importance: str
    score: float
    resolution: float
    created_at: int
    project_id: str | None = None
    conflict_flag: bool = False
    urgency: str = "none"
    deadline_ts: int | None = None
    urgency_expired: bool = False
    bare_entity: bool = False
    embedding_model_version: str = "multilingual-e5-small"
    
    layer: str = "RAM_HOT"
    embedding: np.ndarray | None = None
    implicit_score: float = 0.5
    # Emotion intensity linked to this session (0.0 = no emotion; used in eviction v2)
    intensity: float = 0.0

    # Content Branch classification (set by Observer PersistStep)
    # Values: "content" | "research" | "context" | None (unclassified)
    session_type: str | None = None

    # Full content text (set by Observer PersistStep from pctx.event.text)
    content_full: str | None = None
    # Source role for the session (user/agent, set by Observer from pctx.event.role)
    event_role: str | None = None

    # Vectors of the chunks this session's text was split into (E-2, D2). Kept in RAM
    # so that rebuilding the index after eviction restores them: they live in SQLite
    # too, but a rebuild is synchronous and cannot go to disk, and a rebuilt index
    # without them would silently stop matching anything below the summary level.
    # ~768 bytes per chunk, a few per session — cheap next to what they buy.
    chunk_vectors: list = field(default_factory=list)
