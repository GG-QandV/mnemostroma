# Emotional Patterns Layer — Specification v1.0

> Phase 5.4 | 2026-04-03 | Derived from: MEMORY_MODEL_v2.md, ROADMAP_v2.md § 5.3, ExperienceLayer code
> Status: SPEC — ready for implementation

---

## Purpose

Accumulate long-term emotional patterns of the user over entity tags.
Answer the question: "which topics make this user feel good / bad / conflicted?"

MEMORY_MODEL_v2.md defines this as a layer:
```
Emotional patterns → user emotion patterns (future)
```

---

## Design Decision: Extend ExperienceCluster, not a separate layer

**Options considered:**

| Option | Pros | Cons |
|--------|------|------|
| Separate `EmotionalPatternsIndex` | Clean separation | Duplicate tag-keyed storage, double hydration, double persistence |
| Extend `ExperienceCluster` | One store, one key space, natural join | ExperienceCluster grows, must version DB schema |

**Decision: Extend ExperienceCluster.**

Rationale:
- ExperienceCluster already aggregates per tag — same key space as emotions (emotion → entity → tags)
- Avoids a second RAM index, second SQLite table, second hydration path
- `intuition_signals()` already has TENSION — ATTRACT/REPEL fit naturally alongside it
- One `experience_index.update_emotion()` call in pipeline is simpler than wiring a new index

---

## Data Model

### New fields on ExperienceCluster

```python
@dataclass
class ExperienceCluster:
    # ... existing fields ...

    # Emotional pattern counters (Phase 5.4)
    emotion_positive: int = 0       # count of POSITIVE emotions bound to entities with this tag
    emotion_negative: int = 0       # count of NEGATIVE emotions bound to entities with this tag
    emotion_intensity_sum: float = 0.0  # sum of intensities (for average)
```

### Derived properties

```python
@property
def emotion_count(self) -> int:
    return self.emotion_positive + self.emotion_negative

@property
def emotion_valence(self) -> float:
    """[-1.0, +1.0] — net emotional charge. 0 = neutral / insufficient data."""
    total = self.emotion_positive + self.emotion_negative
    if total == 0:
        return 0.0
    return (self.emotion_positive - self.emotion_negative) / total

@property
def emotion_signal(self) -> Optional[str]:
    """ATTRACT | REPEL | AMBIVALENT | None (insufficient data)."""
    if self.emotion_count < _EMOTION_MIN_SAMPLES:
        return None
    v = self.emotion_valence
    if v >= 0.6:
        return "ATTRACT"
    if v <= -0.6:
        return "REPEL"
    if abs(v) <= 0.3 and self.emotion_count >= _EMOTION_MIN_SAMPLES * 2:
        return "AMBIVALENT"
    return None
```

### Constants

```python
_EMOTION_MIN_SAMPLES = 3   # minimum emotions before signal fires
```

---

## Update Path

### Where emotion data enters

`pipeline.py` after marker returns `CREATE_EMOTION` and the emotion is resolved
(either immediately via `bind_emotion` or via `resolve_pending_emotions`):

```
marker() → CREATE_EMOTION → emotion.pending=False + emotion.ref_entity_id set
    ↓
Look up entity in ram_index → get entity tags (via session brief tags)
    ↓
experience_index.update_emotion(tags, charge, intensity)
```

### New method on ExperienceIndex

```python
def update_emotion(
    self,
    tags: List[str],
    charge: EmotionCharge,
    intensity: float,
) -> None:
    """Record an emotion event against all tags of the bound entity.

    Only POSITIVE and NEGATIVE charges update counters.
    NEUTRAL and UNCERTAIN are ignored (no signal value).
    """
    if charge not in (EmotionCharge.POSITIVE, EmotionCharge.NEGATIVE):
        return
    for tag in tags:
        if tag not in self._clusters:
            self._clusters[tag] = ExperienceCluster(tag=tag, _thresholds=self._thresholds)
        self._clusters[tag].record_emotion(charge, intensity)
```

### New method on ExperienceCluster

```python
def record_emotion(self, charge: EmotionCharge, intensity: float) -> None:
    from .entities import EmotionCharge  # avoid circular at module level
    if charge == EmotionCharge.POSITIVE:
        self.emotion_positive += 1
    elif charge == EmotionCharge.NEGATIVE:
        self.emotion_negative += 1
    self.emotion_intensity_sum += intensity
    self.last_updated = int(time.time())
```

---

## Signal Generation

### New signal types in `intuition_signals()`

Added alongside existing DO_THIS / AVOID_THIS / TENSION:

```python
# ATTRACT: tag reliably produces positive emotions (valence >= 0.6, min 3 samples)
if cluster.emotion_signal == "ATTRACT":
    signals.append({
        "type": "ATTRACT",
        "tag": tag,
        "message": f"Тема «{tag}» устойчиво вызывает позитивный отклик.",
    })

# REPEL: tag reliably produces negative emotions (valence <= -0.6, min 3 samples)
if cluster.emotion_signal == "REPEL":
    signals.append({
        "type": "REPEL",
        "tag": tag,
        "message": f"Тема «{tag}» устойчиво вызывает негативный отклик.",
    })

# AMBIVALENT: mixed emotional signal (|valence| <= 0.3, min 6 samples)
if cluster.emotion_signal == "AMBIVALENT":
    signals.append({
        "type": "AMBIVALENT",
        "tag": tag,
        "message": f"Тема «{tag}» вызывает противоречивые реакции.",
    })
```

Signal priority (when multiple apply to same tag): TENSION > REPEL > AMBIVALENT > ATTRACT > DO_THIS > AVOID_THIS.
Only the highest-priority signal fires per tag.

---

## Storage

### SQLite schema extension

`experiences` table — add 3 columns (migration via ALTER TABLE):

```sql
ALTER TABLE experiences ADD COLUMN emotion_positive INTEGER NOT NULL DEFAULT 0;
ALTER TABLE experiences ADD COLUMN emotion_negative INTEGER NOT NULL DEFAULT 0;
ALTER TABLE experiences ADD COLUMN emotion_intensity_sum REAL NOT NULL DEFAULT 0.0;
```

### DatabaseManager changes

`upsert_experience()` — add new fields to INSERT/UPDATE:

```python
await db.execute("""
    INSERT INTO experiences (tag, session_count, score_sum, conflict_count,
                             last_updated, emotion_positive, emotion_negative,
                             emotion_intensity_sum)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(tag) DO UPDATE SET
        session_count = excluded.session_count,
        score_sum = excluded.score_sum,
        conflict_count = excluded.conflict_count,
        last_updated = excluded.last_updated,
        emotion_positive = excluded.emotion_positive,
        emotion_negative = excluded.emotion_negative,
        emotion_intensity_sum = excluded.emotion_intensity_sum
""", (..., cluster.emotion_positive, cluster.emotion_negative, cluster.emotion_intensity_sum))
```

`load_experience()` — include new columns in SELECT, pass to ExperienceCluster constructor.

### Migration strategy

On bootstrap, `db_manager.check_embedding_dim()` pattern — add similar
`check_experience_schema()` that runs ALTERs if columns are missing (idempotent).

---

## Integration with pipeline.py

### Step 1.5 — NER micro-pipe for emotion tagging

After marker() returns CREATE_ENTITY (step 1), run NER immediately to get entity tags.
This is the only moment where we can accurately tag the entity that emotions are bound to.

**Latency impact: none.**
Currently step 2+4 runs `gather(NER, embed)`. When action=CREATE_ENTITY, embed is
reused from marker (0ms), so NER already runs solo in gather. Moving NER to step 1.5
produces identical wall-clock time — the gather just becomes a pass-through.

```python
# Step 1.5: NER micro-pipe — only when CREATE_ENTITY + resolved emotions present
_entity_tags_for_emotions: List[str] = []
if (mark_result.action == MarkerAction.CREATE_ENTITY
        and ctx.pending_emotions  # there were pending emotions to resolve
        and ctx.models and ctx.models.ner):
    try:
        _ner_entities = await ctx.models.ner.extract_entities(
            text, threshold=ctx.config.importance.ner_score_threshold
        )
        _, _entity_tags_for_emotions = compress_text(text, _ner_entities)
    except Exception as e:
        logger.warning(f"observer: step 1.5 NER failed, emotion tags skipped: {e}")
        _entity_tags_for_emotions = []
```

Then step 2+4 `_run_ner()` reuses the cached result:

```python
async def _run_ner():
    if _entity_tags_for_emotions:          # already computed at 1.5
        return _ner_entities               # reuse, no double NER
    if not (mark_result.action == MarkerAction.CREATE_ENTITY
            and ctx.models and ctx.models.ner):
        return []
    return await ctx.models.ner.extract_entities(
        text, threshold=ctx.config.importance.ner_score_threshold
    )
```

### Step 7c — Emotional pattern update

```python
# 7c. Experience Layer update (existing + § 5.4 addition)
if ctx.experience_index is not None and sb.tags:
    ctx.experience_index.update(
        tags=sb.tags,
        is_continuation=not is_new_entity,
        is_conflict=bool(sb.conflict_flag),
    )
    # § 5.4: Update emotional patterns using entity-accurate tags from step 1.5
    if mark_result.action == MarkerAction.CREATE_ENTITY and _entity_tags_for_emotions:
        for emotion in [e for e in ctx.pending_emotions if not e.pending]:
            # pending list has already been cleared of resolved emotions by this point
            pass  # resolved emotions were in the list BEFORE clear — see note below
```

**Note on resolved emotion access**: `resolve_pending_emotions()` mutates emotions
in-place (sets `pending=False`). After pipeline's `ctx.pending_emotions = [e for e in ... if e.pending]`
the resolved ones are gone from the list. Pipeline must capture them before clearing:

```python
# After marker() returns CREATE_ENTITY:
resolved_emotions = [e for e in ctx.pending_emotions if not e.pending]

# Clear resolved from list (existing logic):
ctx.pending_emotions = [e for e in ctx.pending_emotions if e.pending]

# § 5.4: update emotional patterns (step 7c, tags from step 1.5):
if ctx.experience_index and _entity_tags_for_emotions and resolved_emotions:
    for em in resolved_emotions:
        ctx.experience_index.update_emotion(
            tags=_entity_tags_for_emotions,
            charge=em.charge,
            intensity=em.intensity,
        )
```

---

## MCP / ConductorProxy exposure

`ctx.pulse()` already returns intuition signals. No new MCP tool needed.
New signal types (ATTRACT/REPEL/AMBIVALENT) appear automatically in pulse() output.

---

## Implementation Checklist

```
[ ] ExperienceCluster: add emotion_positive, emotion_negative, emotion_intensity_sum fields
[ ] ExperienceCluster: add record_emotion(charge, intensity) method
[ ] ExperienceCluster: add emotion_count, emotion_valence, emotion_signal properties
[ ] ExperienceCluster: update to_dict() to include emotion fields
[ ] ExperienceIndex: add update_emotion(tags, charge, intensity) method
[ ] ExperienceIndex: update intuition_signals() — ATTRACT / REPEL / AMBIVALENT
[ ] ExperienceIndex.load(): read emotion fields from SQLite rows
[ ] DatabaseManager: add 3 columns to upsert_experience()
[ ] DatabaseManager: add check_experience_schema() migration (ALTER TABLE)
[ ] DatabaseManager: load_experience() includes new columns
[ ] pipeline.py: step 1.5 — NER micro-pipe after CREATE_ENTITY when pending_emotions present
[ ] pipeline.py: capture resolved_emotions before clearing ctx.pending_emotions
[ ] pipeline.py: step 7c — call experience_index.update_emotion(entity_tags, charge, intensity)
[ ] pipeline.py: pass _ner_entities to _run_ner() to avoid double NER execution
[ ] Tests: test_emotional_patterns.py — signal thresholds, valence, ATTRACT/REPEL/AMBIVALENT
[ ] Tests: migration test — old DB without emotion columns → silent zero defaults
```

---

## Out of scope (defer)

- Emotion decay over time (separate from experience decay — add in future)
- Per-source emotion tracking (user vs tool emotions — currently only user)
- Emotion pattern in Dreamer reassessment (add when Dreamer is extended)
- Direct SQLite query API for emotion history (MCP Phase 6)

---

*EMOTIONAL_PATTERNS_SPEC v1.0 | 2026-04-03 | Extends: experience.py ExperienceCluster*
*Depends on: Phase 5.1 (entities.py), 5.2 (pending_emotions), experience.py*
