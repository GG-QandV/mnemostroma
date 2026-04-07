# SPDX-License-Identifier: FSL-1.1-MIT
"""Anchor Layer — irreducible skeleton of every observed event.

An anchor is what remains after full context decay.
Every session produces an anchor at observe() time.
Anchors are never deleted, only their surrounding context decays.
"""
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

logger = logging.getLogger("mnemostroma.subconscious.anchor")


@dataclass
class Anchor:
    """Irreducible event skeleton.
    
    Created at observe() time for every significant session.
    Context around it decays; the anchor itself persists forever.
    """
    anchor_id: str                    # = session_id (1:1)
    session_id: str
    brief: str                        # 50 chars — never decays
    anchor_type: str                  # decision/constraint/milestone/event/observation
    
    # Key facts from entities — sorted by priority, max stored at creation
    # Decay will reduce this list over time, but minimum 1-2 remain forever
    key_facts: List[Dict[str, Any]] = field(default_factory=list)
    # Each fact: {"type": str, "value": str, "score": float, "priority": int}
    
    # Primary flags — set by Observer at creation, reassessed by Dreamer later
    flags: Dict[str, Any] = field(default_factory=lambda: {
        "is_new_entity": True,        # new or continuation of previous
        "continuation_of": None,      # session_id if continuation
        "continuation_depth": 0,      # how many sessions deep
        "mention_type": "focus",      # focus | passing
        "outcome": "pending",         # pending | success | failure | neutral | abandoned
        "user_pin": False,            # user said "remember" / "note this"
        "multi_session": False,       # part of process spanning > 2 sessions
    })
    
    # Decay metadata
    decay_level: int = 0              # 0=full, 1=partial, 2=skeleton, 3=bedrock
    access_count: int = 0             # times "remembered" / resurfaced
    last_accessed_at: int = 0         # last resurface timestamp
    
    # Temporal relation graph — directed links to other anchor/entity IDs
    # {"after": [...], "before": [...], "caused_by": [...], "during": [...]}
    t_rel: Dict[str, Any] = field(default_factory=lambda: {
        "after": [], "before": [], "caused_by": [], "during": []
    })

    # Timestamps
    created_at: int = 0
    updated_at: int = 0
    
    def touch(self) -> None:
        """Record an access (resurface from silt)."""
        self.access_count += 1
        self.last_accessed_at = int(time.time())
        self.updated_at = self.last_accessed_at
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for SQLite JSON fields."""
        return {
            "anchor_id": self.anchor_id,
            "session_id": self.session_id,
            "brief": self.brief,
            "anchor_type": self.anchor_type,
            "key_facts": self.key_facts,
            "flags": self.flags,
            "decay_level": self.decay_level,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
            "t_rel": self.t_rel,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Anchor":
        """Deserialize from SQLite row."""
        if "t_rel" not in data:
            data = {**data, "t_rel": {"after": [], "before": [], "caused_by": [], "during": []}}
        return cls(**data)
