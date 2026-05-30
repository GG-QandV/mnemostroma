# SPDX-License-Identifier: FSL-1.1-MIT
"""Memory Model v2 dataclasses — Entity, Emotion, Atmosphere.

Basis: docs/MEMORY_SPEC_v2.md, docs/MEMORY_MODEL_v2.md
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class EntityType(str, Enum):
    DECISION  = "decision"   # decision made
    FACT      = "fact"       # fact recorded
    CODE      = "code"       # code / artifact
    EVENT     = "event"      # event occurred
    QUESTION  = "question"   # open question
    RESULT    = "result"     # result of action


class SourceType(str, Enum):
    USER  = "user"
    AGENT = "agent"
    TOOL  = "tool"


class ResultType(str, Enum):
    SUCCESS = "success"
    FAIL    = "fail"
    PENDING = "pending"
    NONE    = "none"


class TimeRef(str, Enum):
    PAST    = "past"
    PRESENT = "present"
    FUTURE  = "future"
    UNKNOWN = "unknown"


class Explicitness(str, Enum):
    EXPLICIT = "explicit"   # explicit marker in text
    INFERRED = "inferred"   # derived from position in chain
    LOST     = "lost"       # could not be determined


class EmotionCharge(str, Enum):
    POSITIVE  = "positive"
    NEGATIVE  = "negative"
    NEUTRAL   = "neutral"
    UNCERTAIN = "uncertain"


class MarkerAction(str, Enum):
    CREATE_ENTITY     = "create_entity"
    CREATE_EMOTION    = "create_emotion"
    CREATE_ATMOSPHERE = "create_atmosphere"
    DISCARD           = "discard"


# ---------------------------------------------------------------------------
# Temporal
# ---------------------------------------------------------------------------

@dataclass
class TemporalMarker:
    """Time reference attached to every Entity."""
    gram_time:    TimeRef      # grammatical tense from text
    ref_time:     TimeRef      # real binding (context-resolved)
    explicitness: Explicitness # how the time was determined
    confidence:   float        # 0.0–1.0

    @classmethod
    def unknown(cls) -> TemporalMarker:
        return cls(TimeRef.UNKNOWN, TimeRef.UNKNOWN, Explicitness.LOST, 0.3)


@dataclass
class TemporalRelations:
    """Directed links to other Entity IDs (uuid4 strings)."""
    after:     list[str] = field(default_factory=list)
    before:    list[str] = field(default_factory=list)
    caused_by: list[str] = field(default_factory=list)
    during:    list[str] = field(default_factory=list)

    def all_ids(self) -> list[str]:
        return self.after + self.before + self.caused_by + self.during

    def is_empty(self) -> bool:
        return not any([self.after, self.before, self.caused_by, self.during])


# ---------------------------------------------------------------------------
# Core objects
# ---------------------------------------------------------------------------

@dataclass
class Entity:
    """Primary memory unit — anchors a fact, decision, code, event, etc."""
    # Required
    id:         str            # uuid4
    what:       str            # content text
    type:       EntityType
    source:     SourceType
    t_abs:      int            # unix ms
    temp:       TemporalMarker

    # Temporal graph
    t_rel: TemporalRelations = field(default_factory=TemporalRelations)

    # Optional
    result:     ResultType | None   = None
    atmosphere: str | None         = None   # surrounding context snippet
    importance: float                 = 0.5    # 0.0–1.0, reduced by decay
    embedding:  np.ndarray | None  = field(default=None, repr=False)

    # Access tracking for decay
    last_accessed: int = field(default_factory=lambda: int(time.time() * 1000))

    @classmethod
    def create(
        cls,
        what: str,
        entity_type: EntityType,
        source: SourceType,
        temp: TemporalMarker | None = None,
        **kwargs,
    ) -> Entity:
        now_ms = int(time.time() * 1000)
        return cls(
            id=str(uuid.uuid4()),
            what=what,
            type=entity_type,
            source=source,
            t_abs=now_ms,
            temp=temp or TemporalMarker.unknown(),
            last_accessed=now_ms,
            **kwargs,
        )


@dataclass
class Emotion:
    """User emotional signal — always attached to an Entity (backward or pending)."""
    # Required
    id:        str           # uuid4
    charge:    EmotionCharge
    intensity: float         # 0.0–1.0
    t_abs:     int           # unix ms

    # Entity binding
    ref_entity_id: str | None        = None  # entity id (backward link)
    ref_source:    SourceType | None = None  # whose entity
    pending:       bool                 = False  # True = waiting for entity ahead

    @classmethod
    def create(
        cls,
        charge: EmotionCharge,
        intensity: float,
        ref_entity_id: str | None = None,
        ref_source: SourceType | None = None,
        pending: bool = False,
    ) -> Emotion:
        return cls(
            id=str(uuid.uuid4()),
            charge=charge,
            intensity=intensity,
            t_abs=int(time.time() * 1000),
            ref_entity_id=ref_entity_id,
            ref_source=ref_source,
            pending=pending,
        )


@dataclass
class Atmosphere:
    """Context placeholder — co-occurring signals without a primary entity yet."""
    entity_id:   str | None  # null until bound to an entity
    signals:     list[str]      # co-occurring words / topics
    noise_level: float          # 0.0–1.0
    pending:     bool           # True = waiting for entity
    t_abs:       int            # unix ms

    @classmethod
    def create(cls, signals: list[str], noise_level: float = 0.5) -> Atmosphere:
        return cls(
            entity_id=None,
            signals=signals,
            noise_level=noise_level,
            pending=True,
            t_abs=int(time.time() * 1000),
        )


# ---------------------------------------------------------------------------
# Marker result (output of marker(), replaces filter())
# ---------------------------------------------------------------------------

@dataclass
class MarkerResult:
    """Return value of the marker() function (Phase 2.2)."""
    action:     MarkerAction
    entity:     Entity | None    = None
    emotion:    Emotion | None   = None
    atmosphere: Atmosphere | None = None
    confidence: float               = 1.0

    @classmethod
    def discard(cls) -> MarkerResult:
        return cls(action=MarkerAction.DISCARD, confidence=1.0)
