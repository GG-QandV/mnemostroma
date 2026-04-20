# Spec: Temporal Retrieval v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.B
> Depends on: MatrixSearch (hnsw.py), SQLite storage, SessionBrief schema, config

---

## 1. Overview

Time is a primary retrieval axis in human memory. "What happened yesterday?" and "what did we work on last week?" are natural queries that current semantic and tag search cannot answer. This spec defines two mechanisms:

- **A. `ctx_recent(days)`** — new tool: direct time-based retrieval
- **B. `time_weight` in MatrixSearch** — optional recency bias in semantic scoring

These are independent features that can be enabled separately.

---

## 2. Mechanism A — ctx_recent()

### 2.1 Interface

```python
async def ctx_recent(
    days: float = 7.0,
    by: str = "created",      # "created" | "accessed"
    limit: int = 20,
    ctx: SystemContext,
) -> List[Dict[str, Any]]:
```

**`by="created"`** — sessions observed in the last N days (what happened)
**`by="accessed"`** — sessions retrieved/used in the last N days (what was active)

### 2.2 Data Flow

```
ctx_recent(days=7)
      │
      ├─→ Phase 1: RAM scan
      │     cutoff = now - days * 86400
      │     field = "created_at" if by=="created" else "last_accessed_at"  
      │     results = [sb for sb in ctx.ram_index.values()
      │                if getattr(sb, field, 0) >= cutoff]
      │
      ├─→ Phase 2: SQLite fallback (if RAM results < limit)
      │     remaining = limit - len(results)
      │     known_ids = {sb.session_id for sb in results}
      │     SELECT session_id, brief, importance, created_at, last_accessed_at,
      │            tags, decay_level
      │     FROM sessions
      │     WHERE {field} >= {cutoff}
      │       AND session_id NOT IN ({known_ids})
      │     ORDER BY {field} DESC
      │     LIMIT {remaining}
      │
      ├─→ Phase 3: merge + sort by field DESC
      │
      └─→ return list with decay_level visible (agent knows fidelity)
```

### 2.3 Response Format

```json
[
  {
    "session_id": "sess_abc",
    "brief": "Decided to use SQLite WAL for PersistenceLayer",
    "importance": "critical",
    "created_at": 1744200000,
    "age_days": 1.3,
    "decay_level": 0,
    "tags": ["architecture", "storage"]
  }
]
```

`decay_level` exposed explicitly — agent can judge how much detail to trust.

### 2.4 Location

**New function in:** `src/mnemostroma/tools/read.py`
**Exposed in MCP adapter as:** `ctx_recent`

### 2.5 Known Issues

| Issue | Severity | Resolution |
|---|---|---|
| `last_accessed_at` may be 0 if never re-accessed | Medium | Default to `created_at` if 0 |
| Dissolved sessions in SQLite have reduced `brief` | Medium | Return `decay_level` so agent knows |
| RAM + SQLite merge may return duplicates if session partly evicted | Low | Dedup by `session_id` before return |
| SQLite query uses `cutoff` as Unix timestamp — timezone-safe | Low | Always store UTC, compare UTC |
| `days=0.5` for "last 12 hours" — float support required | Low | float accepted, convert to seconds |

---

## 3. Mechanism B — time_weight in MatrixSearch

### 3.1 Concept

Semantic search currently returns results purely by cosine similarity. Adding time decay makes recent sessions rank higher when meaning is similar — matching human recency bias.

```
score_current  = cosine_similarity(query, stored)
score_weighted = cosine_similarity(query, stored) × time_decay(age_days)
```

### 3.2 Decay Function

```python
def time_decay(age_days: float, half_life: float) -> float:
    """Exponential decay. At age=half_life, score multiplied by 0.5."""
    return math.exp(-age_days * math.log(2) / half_life)

# Examples (half_life=30 days):
# age=0   → 1.00 (no penalty)
# age=30  → 0.50
# age=60  → 0.25
# age=90  → 0.125
```

### 3.3 Exemptions — Critical Constraint

Sessions with `importance in ("critical", "principle")` are **exempt from time decay**. These are architectural decisions and principles that remain equally relevant regardless of age.

```python
decay = (
    1.0
    if sb.importance in ctx.config.temporal_retrieval.time_weight_exempt
    else time_decay(age_days, ctx.config.temporal_retrieval.half_life_days)
)
score = cosine_sim * decay
```

**Without this exemption:** A 6-month-old constraint "no Redis in Core" would rank below a recent irrelevant session. This would be a critical failure mode.

### 3.4 Integration in MatrixSearch

**File:** `src/mnemostroma/memory/hnsw.py`

```python
def search(
    self,
    query_vec: np.ndarray,
    k: int = 10,
    time_weighted: bool = False,
    half_life_days: float = 30.0,
    exempt_importance: tuple = ("critical", "principle"),
) -> List[Tuple[str, float]]:
    ...
    if time_weighted and hasattr(label_meta, "created_at"):
        age_days = (time.time() - label_meta.created_at) / 86400
        importance = getattr(label_meta, "importance", "normal")
        if importance not in exempt_importance:
            score *= time_decay(age_days, half_life_days)
```

`time_weighted=False` by default — feature is opt-in, no regression risk.

### 3.5 Conflict with Dissolution

Dissolution already reduces accessibility of old sessions (evicts from RAM, strips detail). time_weight adds a second age penalty in scoring. Risk of double-penalizing old sessions.

**Resolution:** time_weight applies ONLY to sessions currently in RAM (`decay_level == 0`). Sessions already dissolved (`decay_level > 0`) are in SQLite and not part of MatrixSearch anyway — dissolution already decided their accessibility.

```python
if time_weighted and decay_level == 0:
    score *= time_decay(age_days, half_life)
# decay_level > 0 → session not in MatrixSearch → rule doesn't apply
```

### 3.6 Config

```json
"temporal_retrieval": {
    "ctx_recent_enabled": true,
    "time_weighted_search": false,
    "half_life_days": 30,
    "time_weight_exempt_importance": ["critical", "principle"]
}
```

`time_weighted_search` off by default. Enable explicitly when user wants recency-biased semantic search.

---

## 4. Interaction Between A and B

They are independent but complementary:

- `ctx_recent(days=7)` — "show me what happened last week" (explicit time query, no semantic)
- `ctx_semantic("auth decision")` with `time_weight=True` — "find most relevant recent decision" (semantic + recency bias)

No conflict. `ctx_recent` ignores semantic similarity entirely. `time_weight` never applies to `ctx_recent`.

---

## 5. Tests Required

**ctx_recent:**
- `test_ctx_recent_ram_only()` — all results in RAM, no SQLite needed
- `test_ctx_recent_sqlite_fallback()` — RAM has 2, limit=10 → fetches 8 from SQLite
- `test_ctx_recent_by_accessed()` — by="accessed" uses last_accessed_at
- `test_ctx_recent_decay_level_visible()` — dissolved sessions show decay_level > 0
- `test_ctx_recent_dedup()` — session in both RAM and SQLite → appears once

**time_weight:**
- `test_time_decay_function()` — at half_life → 0.5, at 0 → 1.0
- `test_time_weight_exempt_critical()` — critical session not penalized by age
- `test_time_weight_changes_ranking()` — old relevant vs new less-relevant → new wins when enabled
- `test_time_weight_off_by_default()` — normal search unchanged without flag
