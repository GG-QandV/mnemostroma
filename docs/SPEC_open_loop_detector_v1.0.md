# Spec: Open Loop Detector v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.E
> Depends on: AnchorIndex, Observer pipeline Step 1.5 (Spec 11.A/C shared scan), SystemContext, ctx_active()

---

## 1. Overview

Human working memory surfaces unfinished business automatically when a related topic appears. "We're discussing authentication — and we never closed the decision on token storage." This spec defines the same mechanism: incoming messages automatically surface semantically-related anchors where `outcome == "pending"`.

**Key principle:** No tool call. No agent action. Merged into the existing Step 1.5 scan pass (same embedding, same AnchorIndex iteration). Zero extra ONNX calls.

---

## 2. What It Detects

An anchor qualifies as an "open loop" if ALL of:

| Condition | Value | Rationale |
|---|---|---|
| `anchor.flags["outcome"]` | `"pending"` | Not yet resolved |
| `anchor.anchor_type` | `"decision"` or `"constraint"` | Only load-bearing anchors — not events/observations |
| `similarity >= threshold` | `0.75` (configurable) | Relevant to current message topic |
| cooldown not active | `now - recently_looped[id] >= cooldown_sec` | Prevents repetition |

**Why decision/constraint only:** By default `outcome="pending"` for all new anchors (no outcome signal detected). Without type filter the majority of anchors would qualify — unusable noise.

---

## 3. Architecture — Merged Scan Pass

Open Loop Detector extends the shared scan from Spec 11.C §3.1. Single `_scan_anchors()` function, one O(n) pass over AnchorIndex, three output buckets:

```python
# Single scan → split by threshold + filter:
# sim >= 0.72  AND load-bearing type              → conflict_warnings   (Guardian, Spec 11.C)
# sim >= 0.75  AND any type                       → surfaced_queue      (Surfacing, Spec 11.A)
# sim >= 0.75  AND is_open_loop(anchor)           → open_loops_queue    (this spec)
```

One anchor can appear in multiple buckets (e.g., a pending constraint with high similarity → both `conflict_warnings` and `open_loops_queue`). This is intentional — signals have different semantics.

```
Incoming message
      │
Observer Step 1: embed(message) → embedding_vec  [already exists]
      │
      └─→ Step 1.5: _scan_anchors(embedding_vec, ctx)  [extended from Spec 11.C]
                │
                ├─→ conflict_warnings    (Guardian)
                ├─→ surfaced_queue       (Surfacing)
                └─→ open_loops_queue     [NEW]

ctx_active() [called by agent]:
      ├─→ reads ctx.open_loops_queue
      ├─→ appends as "open_loops" field in response
      └─→ clears ctx.open_loops_queue
```

---

## 4. is_open_loop() Filter

```python
_OPEN_LOOP_TYPES = {"decision", "constraint"}

def is_open_loop(anchor: "Anchor") -> bool:
    return (
        anchor.anchor_type in _OPEN_LOOP_TYPES
        and anchor.flags.get("outcome") == "pending"
        and anchor.embedding is not None
    )
```

---

## 5. _scan_anchors() — Extended Unified Function

**Location:** `src/mnemostroma/subconscious/guardian.py` (extend existing, or extract to `scan.py`)

```python
GUARDIAN_TYPES = {"principle", "constraint", "critical", "decision"}
_OPEN_LOOP_TYPES = {"decision", "constraint"}

async def _scan_anchors(
    embedding: np.ndarray,
    ctx: SystemContext,
) -> None:
    """
    Single pass over AnchorIndex.
    Routes results into ctx.conflict_warnings, ctx.surfaced_queue, ctx.open_loops_queue.
    Mutates ctx in-place. Zero extra ONNX calls.
    """
    now = time.time()
    guardian_threshold = ctx.config.anchor_guardian.threshold       # default 0.72
    surfacing_threshold = ctx.config.associative_surfacing.anchor_threshold  # default 0.75
    open_loop_threshold = ctx.config.open_loop_detector.threshold   # default 0.75
    guardian_cooldown = ctx.config.anchor_guardian.cooldown_sec
    open_loop_cooldown = ctx.config.open_loop_detector.cooldown_sec

    for anchor in ctx.anchor_index.anchors.values():
        if anchor.embedding is None:
            continue

        sim = float(np.dot(embedding, anchor.embedding))

        # Guardian
        if (
            sim >= guardian_threshold
            and anchor.anchor_type in GUARDIAN_TYPES
            and (anchor.anchor_type != "decision" or anchor.decay_level == 0)
        ):
            last_w = ctx.recently_warned.get(anchor.anchor_id, 0)
            if now - last_w >= guardian_cooldown:
                ctx.conflict_warnings.append({
                    "anchor_id": anchor.anchor_id,
                    "brief": anchor.brief,
                    "anchor_type": anchor.anchor_type,
                    "set_at": anchor.created_at,
                    "similarity": round(sim, 3),
                    "decay_level": anchor.decay_level,
                })
                ctx.recently_warned[anchor.anchor_id] = now

        # Surfacing
        if sim >= surfacing_threshold:
            ctx.surfaced_queue.append({
                "type": "anchor",
                "id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": round(sim, 3),
                "decay_level": anchor.decay_level,
            })

        # Open Loop
        if (
            sim >= open_loop_threshold
            and anchor.anchor_type in _OPEN_LOOP_TYPES
            and anchor.flags.get("outcome") == "pending"
        ):
            last_l = ctx.recently_looped.get(anchor.anchor_id, 0)
            if now - last_l >= open_loop_cooldown:
                age_days = (now - anchor.created_at) / 86400
                ctx.open_loops_queue.append({
                    "anchor_id": anchor.anchor_id,
                    "brief": anchor.brief,
                    "anchor_type": anchor.anchor_type,
                    "similarity": round(sim, 3),
                    "created_at": anchor.created_at,
                    "age_days": round(age_days, 1),
                })
                ctx.recently_looped[anchor.anchor_id] = now

    # Sort and cap
    ctx.open_loops_queue.sort(key=lambda x: x["similarity"], reverse=True)
    ctx.open_loops_queue = ctx.open_loops_queue[:ctx.config.open_loop_detector.max_results]
```

**Note:** Replaces the separate `anchor_guardian()` and `associative_scan()` AnchorIndex loops from Specs 11.A and 11.C. Session scan (RAM SessionIndex) from Spec 11.A continues separately in `associative_scan()`.

---

## 6. Observer Pipeline Integration

**File:** `src/mnemostroma/observer/pipeline.py`

Replace the Step 1.5 block from Specs 11.A/C with the unified call:

```python
# Step 1.5 [EXTENDED]: Unified anchor scan — Guardian + Surfacing + Open Loop
if embedding is not None and any([
    ctx.config.anchor_guardian.enabled,
    ctx.config.associative_surfacing.enabled,
    ctx.config.open_loop_detector.enabled,
]):
    from ..subconscious.guardian import _scan_anchors
    from ..subconscious.surfacing import _scan_sessions  # session part of Surfacing

    await asyncio.gather(
        _scan_anchors(embedding, ctx),      # fills conflict_warnings, surfaced_queue, open_loops_queue
        _scan_sessions(embedding, ctx),     # fills surfaced_queue (session hits only)
        return_exceptions=True
    )
```

---

## 7. SystemContext Changes

**File:** `src/mnemostroma/core.py`

```python
open_loops_queue: List[Dict[str, Any]] = field(default_factory=list)
recently_looped: Dict[str, float] = field(default_factory=dict)
# anchor_id → timestamp of last surfacing. In-memory only. Clears on restart.
```

---

## 8. ctx_active() Changes

**File:** `src/mnemostroma/tools/read.py`

```python
async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    result = { ...existing fields... }

    # Open Loop Detector
    open_loops = list(ctx.open_loops_queue)
    ctx.open_loops_queue.clear()
    if open_loops:
        result["open_loops"] = open_loops

    return result
```

---

## 9. Response Format

```json
{
  "open_loops": [
    {
      "anchor_id": "sess_abc123",
      "brief": "Token storage approach for auth — not finalized",
      "anchor_type": "decision",
      "similarity": 0.81,
      "created_at": 1744100000,
      "age_days": 2.4
    },
    {
      "anchor_id": "sess_def456",
      "brief": "Redis banned in Core — but session cache approach still open",
      "anchor_type": "constraint",
      "similarity": 0.77,
      "created_at": 1743900000,
      "age_days": 4.7
    }
  ]
}
```

`open_loops` absent if no pending anchors match current context.

---

## 10. Cooldown Logic

Same pattern as Guardian (Spec 11.C §9):

```
First time anchor X triggers: surface → recently_looped[X] = now
Next message, same anchor: now - recently_looped[X] < cooldown → skip
After cooldown: fires again if still triggered
```

Default cooldown: `7200s` (2 hours) — longer than Guardian's 1h because open loops are informational, not critical constraint violations.

`recently_looped` is in-memory only. Clears on daemon restart.

**Cap:** `recently_looped` capped at 1000 entries, evict oldest. Same as `recently_warned`.

---

## 11. Config

```json
"open_loop_detector": {
    "enabled": true,
    "threshold": 0.75,
    "cooldown_sec": 7200,
    "max_results": 5
}
```

---

## 12. Known Issues

| Issue | Severity | Resolution |
|---|---|---|
| Most anchors have `outcome="pending"` by default | High | Type filter (decision/constraint only) reduces noise significantly |
| Old anchors without embedding skip silently | Medium | Guard: `if anchor.embedding is None: continue` |
| One-turn lag (async, same as Guardian/Surfacing) | Medium | Accepted — no same-turn Layer 1 equivalent |
| A pending decision may persist years if never resolved | Low | Exposed via `age_days` — agent can judge relevance |
| `recently_looped` grows unbounded | Low | Cap at 1000, evict oldest |
| Open loop also in `surfaced` (same anchor) | Low | Intentional — different semantic meaning, different field |

---

## 13. Tests Required

- `test_open_loop_fires_on_pending_decision()` — pending decision anchor + relevant embedding → in open_loops
- `test_open_loop_skips_success_outcome()` — outcome="success" → never in open_loops
- `test_open_loop_skips_observation_type()` — anchor_type="observation" → never in open_loops
- `test_open_loop_respects_cooldown()` — same anchor, second call within 2h → not repeated
- `test_open_loop_threshold()` — sim 0.74 → miss, sim 0.76 → hit
- `test_open_loop_max_results()` — 10 matching anchors → returns only 5
- `test_open_loop_queue_cleared_after_ctx_active()` — queue empty after ctx_active() call
- `test_open_loop_absent_if_empty()` — no pending anchors → key not in response
- `test_unified_scan_all_three_buckets()` — one anchor matching all three signals → appears in conflict_warnings, surfaced_queue, and open_loops_queue
