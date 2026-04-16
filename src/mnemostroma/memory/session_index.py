# SPDX-License-Identifier: FSL-1.1-MIT
from dataclasses import dataclass
from typing import List, Optional
import numpy as np

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
    tags: List[str]
    importance: str
    score: float
    resolution: float
    created_at: int
    
    # v1.3 / v1.4 fields
    conflict_flag: bool = False
    urgency: str = "none"
    deadline_ts: Optional[int] = None
    urgency_expired: bool = False
    bare_entity: bool = False
    embedding_model_version: str = "multilingual-e5-small"
    
    layer: str = "RAM_HOT"
    embedding: Optional[np.ndarray] = None
    implicit_score: float = 0.5
    # Emotion intensity linked to this session (0.0 = no emotion; used in eviction v2)
    intensity: float = 0.0
