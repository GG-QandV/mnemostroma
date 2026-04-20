# Mnemostroma Memory Model v2

> Detailed model — between schema and specification

---

## Three Core Objects

### 1. ENTITY

The memory anchor. Everything else attaches to it.

**Required fields:**

| Field    | Type      | Values                                                  | Description                             |
| -------- | --------- | ------------------------------------------------------- | --------------------------------------- |
| `id`     | string    | uuid                                                    | Unique identifier                       |
| `what`   | string    | —                                                       | Content: fact, decision, object, action |
| `type`   | enum      | decision \| fact \| code \| event \| question \| result | Entity type                             |
| `source` | enum      | user \| agent \| tool                                   | Who produced it                         |
| `t_abs`  | timestamp | unix ms                                                 | When recorded (absolute)                |
| `temp`   | object    | see below                                               | Temporal marker (always required)       |

**Temporal marker — required block:**

```
temp:
  gram_time    : past | present | future | unknown
  ref_time     : past | present | future | unknown
  explicitness : explicit | inferred | lost
  confidence   : 0.0–1.0
```

> `gram_time`   — what the grammar says ("was", "will be", or nothing)
> `ref_time`    — the real time binding, inferred from chain context
> `lost`        — entity exists, time not recognized and not derivable from chain

**Temporal relations (filled as connections are found):**

```
t_rel:
  after    : [id]   — occurred after these entities
  before   : [id]   — occurred before these entities
  caused_by: [id]   — was caused by these entities
  during   : [id]   — was concurrent with these entities
```

> Empty `t_rel` is valid at creation — filled as connections are discovered.
> But `temp` is always required, even when `explicitness=lost`.

**Optional fields:**

| Field        | Type   | Values                             | Description                                      |
| ------------ | ------ | ---------------------------------- | ------------------------------------------------ |
| `result`     | enum   | success \| fail \| pending \| none | Outcome if applicable                            |
| `atmosphere` | string | —                                  | Surrounding context: noise, co-occurring signals |

**Decay:**

```
importance decreases over time if:
  no accesses to the entity itself
  AND no accesses to the entity's context (related entities, atmosphere)
```

---

### 2. EMOTION

> User only. Evaluation of a result (almost always) or expectation of a result (rarely).

**All fields:**

| Field           | Type         | Values                                       | Description                             |
| --------------- | ------------ | -------------------------------------------- | --------------------------------------- |
| `id`            | string       | uuid                                         | —                                       |
| `charge`        | enum         | positive \| negative \| neutral \| uncertain | Signal quality                          |
| `intensity`     | float        | 0.0–1.0                                      | Signal strength                         |
| `ref_entity_id` | string\|null | entity id                                    | What it points to                       |
| `ref_source`    | enum         | agent \| user \| tool \| context             | Whose entity                            |
| `pending`       | bool         | —                                            | true = entity not yet seen, awaiting it |
| `t_abs`         | timestamp    | unix ms                                      | —                                       |

**Reference frequency:**

```
agent   → most frequent   (reaction to agent's response/action)
user    → less frequent   (re-evaluation of own statement)
context → rare            (reaction to the situation as a whole, no specific entity)
```

**Binding direction:**

```
almost always → backward in chain (evaluation of what already happened)
rarely        → forward (expectation of what has not yet happened)
```

---

### 3. ATMOSPHERE

> Context around an entity. Optional when an entity exists.
> Required when a time marker is present but no entity is found.

| Field         | Type         | Values     | Description                                   |
| ------------- | ------------ | ---------- | --------------------------------------------- |
| `entity_id`   | string\|null | id \| null | Anchor (null until entity is found)           |
| `signals`     | []string     | —          | Co-occurring words/topics                     |
| `noise_level` | float        | 0.0–1.0    | How noisy the context is                      |
| `pending`     | bool         | —          | true = waiting for an entity (past or future) |
| `t_abs`       | timestamp    | unix ms    | —                                             |

---

## Relation Rules

```
EMOTION.ref_entity_id   → ENTITY.id      (almost always backward in chain)
ATMOSPHERE.entity_id    → ENTITY.id      (null until entity is found)
ENTITY.t_rel.*          → [ENTITY.id]    (graph, any direction)
```

---

## Discard Rules

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ entity │ emotion │ time marker │ decision                                     │
├──────────────────────────────────────────────────────────────────────────────┤
│  none  │  none   │    none     │ GARBAGE → discard                            │
│        │         │             │                                              │
│  none  │  none   │   present   │ atmosphere exists, link to entity lost       │
│        │         │             │ OR user expected — agent gave no result      │
│        │         │             │ → create ATMOSPHERE, pending=true            │
│        │         │             │                                              │
│  none  │ present │    none     │ time marker likely future                    │
│        │         │             │ or lost/not recognized                       │
│        │         │             │ → create EMOTION, pending=true               │
│        │         │             │   ref_time=future, confidence=0.4            │
│        │         │             │                                              │
│ present│  none   │    none     │ time lost/not recognized                     │
│        │         │             │ → create ENTITY                              │
│        │         │             │   explicitness=lost, confidence=0.3          │
│        │         │             │   time refined from chain later              │
│        │         │             │                                              │
│ present│ present │    any      │ → create ENTITY + EMOTION, link them         │
│        │         │             │   decay lowers importance if no accesses     │
│        │         │             │   to either entity or its context            │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Hard discard at input (before any processing):**

```
empty message            → discard
< 5 characters, no structure → discard
everything else          → into RAM with marking
```

---

## Incoming Stream — Two Paths by Role

```
role=user →
  minimal structural filter (<1ms)
  almost always passes (even profanity = context and emotion)
  importance = user_intent by default

role=agent|assistant →
  full semantic marker
  structural pre-filter + anchor vectors (e5-small)
  aggressive entity type classification
```

> The marker does not discard — it marks. Everything that passes hard discard enters RAM.

---

## Temporal Inference Algorithm

```
1. Explicit marker present (was/will/yesterday/will/already/yet) →
     explicitness = explicit
     confidence = 1.0

2. No explicit marker — look at position in chain:

   a) after an entity in the chain →
        ref_time = past
        explicitness = inferred
        confidence = 0.8

   b) before an expected entity →
        ref_time = future
        explicitness = inferred
        confidence = 0.6

   c) no entities nearby →
        ref_time = unknown
        explicitness = lost
        confidence = 0.3
```

> **Multilingual note:** grammatical present tense often means past
> ("not funny" = evaluation of something that already happened).
> Chain context overrides grammar. Missing tense markers are normal, not an error.
> This applies across RU, EN, UA and other languages the system processes.

---

## Emotion Binding Algorithm

```
received an emotion →

  1. Look backward in chain (N last entities, all sources):
     a) last agent entity  → most likely candidate
     b) last user entity   → if no agent entity
     c) found → ref_entity_id = found, pending = false

  2. Not found backward →
     pending = true
     when next entity appears → bind, close

  3. General context →
     ref_source = context
     ref_entity_id = null
     pending = false
```

---

## RAM — Working Memory

```
Everything that passes hard discard → enters RAM with marking

On capacity hit:
  low importance + no reinforcements + no graph edges → eviction
  evicted with intensity > 0   → flush to SQLite before deletion
  evicted with intensity = 0   → delete permanently
```

---

## Consolidation — The Only Place for Permanence Decisions

```
high importance              → promote to SQLite
high intensity               → promote (even with low importance)
high novelty                 → promote
confirmed by multiple refs   → promote
all low + no edges           → decay → forget
```

---

## Layers (on top of structure, do not change it)

```
Experience Layer     → patterns over entities
HNSW / vectors       → semantic search over entities
Continuation chains  → continuation graph via t_rel
Emotional patterns   → user emotion patterns (future)
Decay / TTL          → fading in SQLite
```

---

*Version: 2.1 | Date: 2026-04-02 | Status: detailed model, pre-spec*
