# Feedback Loop — Спецификация v1.5 (Implicit)
## Mnemostroma | Статус: ЗАФИКСИРОВАНО | Дата: 2026-03-24

---

## 1. Принцип

Two-phase approach:
- **v1.5 (this file):** IMPLICIT feedback — system observes agent behavior to infer usefulness
- **v2.0 (future):** EXPLICIT feedback — agent calls `ctx.feedback(session_id, signal)`

Core insight: if agent retrieves a session and then generates output mentioning its entities → the context was useful. No agent code changes needed.

---

## 2. Implicit Feedback Signals (v1.5)

Four signal types with corresponding weights:

| # | Signal | Weight | Trigger Condition |
|---|--------|--------|-------------------|
| 1 | `USE` | `1.0` | Agent called `ctx.get(id)` **or** `ctx.semantic()` returned this session in top-5 AND agent continued working (not immediately called another semantic query) |
| 2 | `DEEP_USE` | `1.5` | Agent called `ctx.full(id)` — requested full content, not just brief |
| 3 | `IGNORE` | `-0.5` | Session appeared in `ctx.semantic()` top-5 but agent called `ctx.semantic()` again within 5 seconds (implicit "not useful") |
| 4 | `REVISIT` | `2.0` | Same session retrieved 3+ times in the same working session |

---

## 3. use_count → Score Correlation

After 100+ sessions: run **weekly correlation analysis**:

- Calculate **Pearson correlation** between `use_count` and `initial_score` for each session
- If correlation `< 0.4` → Score weights need recalibration
- Adjust `α/β/γ` via gradient-free optimization (`scipy.optimize.minimize`) to maximize correlation
- This is the **v2.0 preparation step**

---

## 4. Implementation

Where each signal is captured:

| Signal | Capture Point | Action |
|--------|--------------|--------|
| `USE` | `ctx.get()` and `ctx.semantic()` — already called | Add `use_count++` and update timestamp |
| `DEEP_USE` | `ctx.full()` | Add `deep_use_count` field to SQLite, increment on call |
| `IGNORE` | Observer event loop | Track consecutive semantic queries; detect rapid re-query pattern (< 5s) |
| `REVISIT` | Consolidation Worker | Count same `session_id` in session's `use_history` within time window |

### New SQLite Fields

```sql
ALTER TABLE sessions ADD COLUMN deep_use_count INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN last_use_ts   INTEGER;
ALTER TABLE sessions ADD COLUMN implicit_score REAL    DEFAULT 0.5;
```

---

## 5. implicit_score Calculation

```python
def update_implicit_score(session_id, signal_type, ram_index):
    weights = {"USE": 1.0, "DEEP_USE": 1.5, "IGNORE": -0.5, "REVISIT": 2.0}
    w = weights.get(signal_type, 0)
    current = ram_index[session_id].get("implicit_score", 0.5)
    # Exponential moving average, alpha=0.1
    new_score = current * 0.9 + (0.5 + w * 0.1)
    ram_index[session_id]["implicit_score"] = max(0.0, min(1.0, new_score))
```

**EMA rationale:** `alpha=0.1` gives slow decay — recent signals matter more but do not cause abrupt swings. Score is clamped to `[0.0, 1.0]`.

---

## 6. v2.0 Placeholder — Explicit Feedback

Future `ctx.feedback()` API (not implemented in v1.5):

```python
ctx.feedback(session_id, signal)
# signal: "useful" | "stale" | "wrong" | "missing"
```

| Signal | Effect |
|--------|--------|
| `"useful"` | `implicit_score += 0.2`, protect from eviction |
| `"stale"` | Accelerate dissolution (`lambda × 2.0`) |
| `"wrong"` | Set `conflict_flag = True`, flag for review |
| `"missing"` | Log gap in coverage, increment `miss_counter` |

---

## 7. Score Integration

How `implicit_score` feeds back into the main Score formula:

**Base formula:** `Score = α×R + β×T + γ×I` where `α=0.5`, `β=0.3`, `γ=0.2`

**Adjusted relevance:**
```
R_adjusted = R × (0.7 + 0.3 × implicit_score)   # range: [0.35·R, R]
```

- Sessions with consistent `IGNORE` signals → `R_adjusted` drops → naturally evicted during consolidation
- Sessions with `REVISIT` signals → `implicit_score` near 1.0 → `R_adjusted ≈ R` (full weight preserved)
- The adjustment is non-destructive: `implicit_score=0.5` (neutral) yields `R_adjusted = 0.85×R`

---

## 8. Метрики

```python
feedback_metrics = {
    "use_signals_today":        0,
    "deep_use_signals_today":   0,
    "ignore_signals_today":     0,
    "revisit_signals_today":    0,
    "avg_implicit_score":       0.0,
    "score_correlation":        0.0,   # Pearson, recalculated weekly
    "sessions_below_threshold": 0,     # implicit_score < 0.2
}
```

These counters reset daily. `score_correlation` is recomputed by the weekly Consolidation Worker job (see §3). `sessions_below_threshold` feeds eviction prioritization.

---

*Mnemostroma | feedback_loop_specification v1.5 | 2026-03-24*
*WP-01 закрыт частично: implicit feedback реализован. Explicit feedback → v2.0*
