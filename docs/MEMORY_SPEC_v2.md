# Mnemostroma Memory Specification v2

> Working specification. Basis: MEMORY_MODEL_v2.md
> Version: 2.0 | Date: 2026-04-02

---

## 1. Data Objects

### 1.1 Entity

```python
@dataclass
class Entity:
    # Required
    id:          str                    # uuid4
    what:        str                    # content
    type:        EntityType             # entity type
    source:      SourceType             # who produced it
    t_abs:       int                    # unix ms
    temp:        TemporalMarker         # time marker (always required)

    # Temporal relations (graph)
    t_rel:       TemporalRelations      # links to other entities

    # Optional
    result:      ResultType | None      # outcome
    atmosphere:  str | None             # surrounding context
    importance:  float                  # 0.0–1.0, reduced by decay
    embedding:   np.ndarray | None      # vector for HNSW


class EntityType(str, Enum):
    DECISION   = "decision"    # decision made
    FACT       = "fact"        # fact recorded
    CODE       = "code"        # code/artifact
    EVENT      = "event"       # event occurred
    QUESTION   = "question"    # open question
    RESULT     = "result"      # result of action


class SourceType(str, Enum):
    USER       = "user"
    AGENT      = "agent"
    TOOL       = "tool"


class ResultType(str, Enum):
    SUCCESS    = "success"
    FAIL       = "fail"
    PENDING    = "pending"
    NONE       = "none"
```

### 1.2 TemporalMarker

```python
@dataclass
class TemporalMarker:
    gram_time:    TimeRef               # grammatical time from text
    ref_time:     TimeRef               # real binding (from context)
    explicitness: Explicitness          # explicit | inferred | lost
    confidence:   float                 # 0.0–1.0


@dataclass
class TemporalRelations:
    after:      list[str] = field(default_factory=list)   # [entity_id]
    before:     list[str] = field(default_factory=list)
    caused_by:  list[str] = field(default_factory=list)
    during:     list[str] = field(default_factory=list)


class TimeRef(str, Enum):
    PAST        = "past"
    PRESENT     = "present"
    FUTURE      = "future"
    UNKNOWN     = "unknown"


class Explicitness(str, Enum):
    EXPLICIT    = "explicit"    # explicit marker in text
    INFERRED    = "inferred"    # derived from position in chain
    LOST        = "lost"        # could not be determined
```

### 1.3 Emotion

```python
@dataclass
class Emotion:
    # Required
    id:           str                   # uuid4
    charge:       EmotionCharge         # signal quality
    intensity:    float                 # 0.0–1.0
    t_abs:        int                   # unix ms

    # Entity binding
    ref_entity_id:  str | None          # entity id (almost always backward)
    ref_source:     SourceType | None   # whose entity
    pending:        bool = False        # True = waiting for entity ahead


class EmotionCharge(str, Enum):
    POSITIVE    = "positive"
    NEGATIVE    = "negative"
    NEUTRAL     = "neutral"
    UNCERTAIN   = "uncertain"
```

### 1.4 Atmosphere

```python
@dataclass
class Atmosphere:
    entity_id:    str | None            # null until entity is found
    signals:      list[str]             # co-occurring words/topics
    noise_level:  float                 # 0.0–1.0
    pending:      bool                  # True = waiting for entity
    t_abs:        int                   # unix ms
```

---

## 2. Incoming Stream — Marking by Role

### 2.1 Hard Discard (before marking)

```
len(text.strip()) < 5  →  discard
text.strip() == ""     →  discard
```

### 2.2 Path by Role

```
role=user →
    structural_only_filter(text)
    importance = USER_INTENT by default
    almost always passes (including profanity, emoji, short replies)

role=agent | assistant →
    structural_prefilter(text)          # <1ms, sync
    semantic_marker(text, embedding)    # ~5ms, async, e5-small
    full classification
```

### 2.3 Semantic Marker — Anchor Vectors

Computed once at startup, stored in `SystemContext`.
Anchor texts are language-agnostic — cosine similarity works across all
languages the e5-small model supports (RU, EN, UA, DE, ZH, etc.):

```python
ANCHORS = {
    EntityType.DECISION:  "critical decision chosen selected rejected forbidden",
    EntityType.FACT:      "important fact requirement dependency we use",
    EntityType.CODE:      "code function class implementation artifact",
    EntityType.EVENT:     "event happened occurred completed failed",
    EntityType.QUESTION:  "question unclear need to check unknown",
    EntityType.RESULT:    "result outcome success failure done finished",
    "principle":          "never always rule non-negotiable architectural principle",
    "urgency":            "deadline urgent today tomorrow asap by end of day",
    "emotion":            "great terrible wrong not working finally works",
}
```

Classification: `argmax(cosine(embedding, anchor_vector))` across all anchors.

---

## 3. Object Creation Rules

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ entity │ emotion │ time marker │ action                                       │
├──────────────────────────────────────────────────────────────────────────────┤
│  none  │  none   │    none     │ DISCARD                                      │
│  none  │  none   │   present   │ Atmosphere(pending=True)                     │
│        │         │             │ link to past/future entity lost              │
│  none  │ present │    none     │ Emotion(pending=True,                        │
│        │         │             │         ref_time=FUTURE, confidence=0.4)     │
│ present│  none   │    none     │ Entity(temp.explicitness=LOST,               │
│        │         │             │        temp.confidence=0.3)                  │
│        │         │             │ time refined from chain later                │
│ present│ present │    any      │ Entity + Emotion, link ref_entity_id         │
│        │         │             │ decay lowers importance if no accesses       │
│        │         │             │ to either entity or its context              │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Temporal Inference Algorithm

```python
def infer_temporal(text: str, chain: list[Entity]) -> TemporalMarker:

    # 1. Explicit markers (language-agnostic detection)
    if has_explicit_past(text):     # was, before, yesterday, previously,
                                    # было, раньше, вчера, previously
        return TemporalMarker(PAST, PAST, EXPLICIT, 1.0)
    if has_explicit_future(text):   # will, tomorrow, next,
                                    # будет, завтра, потом
        return TemporalMarker(FUTURE, FUTURE, EXPLICIT, 1.0)

    # 2. Position in chain (context overrides grammar)
    if chain:
        last = chain[-1]
        # After an entity → almost always evaluation of past
        return TemporalMarker(PRESENT, PAST, INFERRED, 0.8)

    if pending_entity_expected(chain):
        # Before an expected entity → prediction/expectation
        return TemporalMarker(PRESENT, FUTURE, INFERRED, 0.6)

    # 3. Unknown
    return TemporalMarker(UNKNOWN, UNKNOWN, LOST, 0.3)
```

> **Multilingual note:** in Russian (and some other languages) grammatical
> present tense often means evaluation of the past.
> "не работает" after an event = "did not work". Chain context decides.
> The algorithm processes multilingual input — grammar rules vary,
> chain position is universal.

---

## 5. Emotion Binding Algorithm

```python
def bind_emotion(emotion: Emotion, chain: list[Entity]) -> Emotion:

    # Look backward: agent → user → tool
    for source in [SourceType.AGENT, SourceType.USER, SourceType.TOOL]:
        candidates = [e for e in reversed(chain) if e.source == source]
        if candidates:
            emotion.ref_entity_id = candidates[0].id
            emotion.ref_source = source
            emotion.pending = False
            return emotion

    # Not found → wait ahead
    emotion.pending = True
    return emotion


def resolve_pending_emotions(new_entity: Entity, pending: list[Emotion]):
    """Called when a new entity appears."""
    for emotion in pending:
        emotion.ref_entity_id = new_entity.id
        emotion.ref_source = new_entity.source
        emotion.pending = False
```

---

## 6. Decay

```python
def apply_entity_decay(entity: Entity, ctx: SystemContext) -> float:
    """
    Lowers importance if there are no accesses to the entity
    or to its context (related entities).
    """
    days_inactive = (now() - entity.last_accessed) / 86400
    context_accessed = any(
        ctx.was_accessed(rel_id)
        for rel_id in entity.t_rel.all_ids()
    )
    if days_inactive >= threshold and not context_accessed:
        entity.importance = max(0.0, entity.importance - rate * days_inactive)
    return entity.importance
```

---

## 7. RAM and Consolidation

### RAM Eviction (on capacity hit)

```
priority = importance × (1 + intensity) × recency_factor

evicted: min(priority) from non-pinned entities
evicted with intensity > 0   → flush to SQLite
evicted with intensity = 0   → delete permanently
```

### Consolidation (background process)

```
promote to long-term SQLite:
  importance > threshold
  OR intensity > 0.7
  OR novelty > 0.8
  OR confirmed_by_refs >= 2

decay → forget:
  importance < min_threshold
  AND intensity = 0
  AND no incoming refs from other entities
```

---

## 8. Layers (on top of structure)

| Layer | What it does | Depends on |
|-------|-------------|------------|
| HNSW | Semantic search over Entity.embedding | Entity |
| Experience | Patterns of entity tags and types | Entity.type, Entity.t_rel |
| Continuation | Continuation graph between sessions | Entity.t_rel, HNSW |
| Emotional patterns | User emotion patterns over time | Emotion, Entity.result |
| Decay/TTL | Fading in SQLite | importance, intensity, refs |

---

## 9. Marker Interface (replaces filter)

```python
async def marker(
    text:       str,
    role:       SourceType,
    session_id: str,
    ctx:        SystemContext,
) -> MarkerResult:
    """
    Replaces deterministic_filter.
    Does not discard — marks.
    Returns: entity | emotion | atmosphere | discard
    """
```

```python
@dataclass
class MarkerResult:
    action:      MarkerAction           # create_entity | create_emotion |
                                        # create_atmosphere | discard
    entity:      Entity | None
    emotion:     Emotion | None
    atmosphere:  Atmosphere | None
    confidence:  float
```

---

*Version: 2.0 | Date: 2026-04-02 | Status: specification*
*Basis: MEMORY_MODEL_v2.md*
