# SPDX-License-Identifier: FSL-1.1-MIT
"""In-memory anchor index. Holds up to 1000 anchors in RAM.

Eviction: oldest by last_accessed_at when capacity exceeded.
Evicted anchors remain in SQLite forever.
"""
import logging
import time
from typing import Dict, List, Optional, Any
from .anchor import Anchor

logger = logging.getLogger("mnemostroma.subconscious.anchor_index")

# Fact priority for key_facts selection
FACT_PRIORITY: Dict[str, int] = {
    "decision": 1,
    "решение": 1,
    "prohibition": 1,
    "запрет": 1,
    "ban": 1,
    "person": 2,
    "человек": 2,
    "organization": 2,
    "организация": 2,
    "per": 2,
    "org": 2,
    "technology": 3,
    "технология": 3,
    "tech": 3,
    "address": 3,
    "loc": 3,
    "date": 4,
    "дата": 4,
}

DEFAULT_MAX_CAPACITY = 1000


class AnchorIndex:
    """RAM-resident anchor index.
    
    Capacity: up to 1000 anchors (~200KB RAM).
    When full, evicts oldest by last_accessed_at to SQLite.
    """
    
    def __init__(self, max_capacity: int = DEFAULT_MAX_CAPACITY):
        self._anchors: Dict[str, Anchor] = {}  # anchor_id → Anchor
        self._max_capacity = max_capacity
    
    def __len__(self) -> int:
        return len(self._anchors)
    
    def __contains__(self, anchor_id: str) -> bool:
        return anchor_id in self._anchors
    
    @property
    def anchors(self) -> Dict[str, Anchor]:
        """Public read-only view of internal anchor map."""
        return self._anchors

    def get(self, anchor_id: str) -> Optional[Anchor]:
        """Get anchor by id. Does NOT count as access (read ≠ resurface)."""
        return self._anchors.get(anchor_id)
    
    def resurface(self, anchor_id: str) -> Optional[Anchor]:
        """Get anchor AND record access (pulled from silt)."""
        anchor = self._anchors.get(anchor_id)
        if anchor:
            anchor.touch()
        return anchor
    
    def put(self, anchor: Anchor) -> Optional[Anchor]:
        """Add anchor to index.
        
        Returns:
            Evicted anchor if capacity exceeded, else None.
            Caller must persist evicted anchor to SQLite.
        """
        evicted = None
        
        if (
            anchor.anchor_id not in self._anchors 
            and len(self._anchors) >= self._max_capacity
        ):
            evicted = self._evict_oldest()
        
        self._anchors[anchor.anchor_id] = anchor
        return evicted
    
    def query_by_type(self, anchor_type: str) -> List[Anchor]:
        """Get all anchors of given type. For ctx.anchors(type)."""
        return [
            a for a in self._anchors.values() 
            if a.anchor_type == anchor_type
        ]
    
    def query_by_flag(self, flag_name: str, flag_value: Any = True) -> List[Anchor]:
        """Get anchors by flag value."""
        return [
            a for a in self._anchors.values()
            if a.flags.get(flag_name) == flag_value
        ]
    
    def all(self) -> List[Anchor]:
        """All anchors in RAM. For Dreamer iteration."""
        return list(self._anchors.values())
    
    def _evict_oldest(self) -> Anchor:
        """Remove anchor with oldest last_accessed_at."""
        if not self._anchors:
            return None
            
        oldest_id = min(
            self._anchors,
            key=lambda k: self._anchors[k].last_accessed_at
        )
        evicted = self._anchors.pop(oldest_id)
        logger.info(
            "anchor.evict | id=%s type=%s age_days=%d access_count=%d",
            evicted.anchor_id,
            evicted.anchor_type,
            (int(time.time()) - evicted.created_at) // 86400,
            evicted.access_count,
        )
        return evicted
    
    @staticmethod
    def build_key_facts(
        entities: List[Dict[str, Any]], 
        max_facts: int = 5
    ) -> List[Dict[str, Any]]:
        """Select key facts from entities, ranked by type priority.
        
        At creation time we keep up to max_facts.
        Decay will reduce this later.
        """
        prioritized = []
        for e in entities:
            etype = e.get("type", "")
            priority = FACT_PRIORITY.get(etype, 5)
            prioritized.append({
                "type": etype,
                "value": e.get("value", ""),
                "score": e.get("score", 0.0),
                "priority": priority,
            })
        
        # Sort: priority asc (1=most important), then score desc
        prioritized.sort(key=lambda f: (f["priority"], -f["score"]))
        return prioritized[:max_facts]
    
    @staticmethod
    def infer_anchor_type(
        importance: str, 
        entities: List[Dict[str, Any]]
    ) -> str:
        """Determine anchor type from importance + entities."""
        entity_types = {e.get("type", "") for e in entities}
        
        if "decision" in entity_types or "решение" in entity_types:
            return "decision"
        if (
            "prohibition" in entity_types 
            or "ban" in entity_types 
            or "запрет" in entity_types
        ):
            return "constraint"
        if importance == "critical":
            return "milestone"
        if "date" in entity_types or "дата" in entity_types:
            return "event"
        return "observation"
