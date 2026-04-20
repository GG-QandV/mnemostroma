# Spec: Anchor Guardian v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.C
> Depends on: AnchorIndex (anchor_index.py), Observer pipeline, SystemContext, ctx_active()

---

## 1. Overview

Anchor constraint checking must be **unconscious** — like human intuition that stops you from suggesting something that violates an established principle. The agent should not call an explicit tool. The system fires automatically when incoming context triggers an anchor conflict.

**Key principle:** No tool call. No agent action. Anchor Guardian runs in Observer pipeline, surfaces warnings through ctx_active() automatically.

---

## 2. What It Checks

Not all anchors. Only the ones that are permanent and load-bearing:

| Anchor Type | Check | Rationale |
|---|---|---|
| `principle` | Always | Never decays, defines permanent rules |
| `constraint` | Always | Hard limits on architecture/approach |
| `critical` (decision) | Always if `decay_level == 0` | Recent critical decisions |
| `decision` | Only if `decay_level == 0` | Fresh decisions only |
| `milestone` | Never | Historical, not constraining |
| `observation` | Never | Too noisy |

---

## 3. Architecture

```
Incoming message
      │
Observer pipeline Step 1: embed(message) → embedding_vec  [already exists]
      │
      ├─→ Step 1.5 [NEW]: anchor_guardian(embedding_vec, ctx)
      │         │
      │         ├─→ scan qualifying anchors (see table above)
      │         ├─→ cosine similarity vs each anchor.embedding
      │         ├─→ threshold: 0.72 (lower than surfacing — miss < false positive)
      │         ├─→ cooldown check: skip if warned < cooldown_sec ago
      │         ├─→ conflict detected → ctx.conflict_warnings.append(warning)
      │         └─→ update ctx.recently_warned[anchor_id] = now
      │
      └─→ Step 2+: existing pipeline continues unchanged

ctx_active() [called by agent]:
      ├─→ Layer 1: keyword pre-check against qualifying anchor briefs (sync, <1ms)
      ├─→ reads ctx.conflict_warnings (from Layer 2 async)
      ├─→ merges Layer 1 + Layer 2 results
      ├─→ appends as "conflict_warnings" field in response
      └─→ clears ctx.conflict_warnings
```

### 3.1 Shared Scan Pass with Workflow 1 (Surfacing)

Both Anchor Guardian (this spec) and Associative Surfacing (Spec 11.A) scan AnchorIndex using the same embedding vector. To avoid double computation:

```python
# Single scan pass → split by threshold:
# similarity >= 0.72  AND anchor is constraint/principle/critical → conflict_warnings
# similarity >= 0.75  AND anchor is any type                     → surfaced_queue
# (a result can appear in both if similarity >= 0.78)
```

Single call to `anchor_index_scan(embedding)` returns all similarities. Then threshold routing splits results. Implemented in a shared `_scan_anchors(embedding, ctx)` function called from pipeline step 1.5.

---

## 4. anchor_guardian() — New Module

**Location:** `src/mnemostroma/subconscious/guardian.py` (new file)

```python
GUARDIAN_TYPES = {"principle", "constraint", "critical", "decision"}

async def anchor_guardian(
    embedding: np.ndarray,
    ctx: SystemContext,
    threshold: float = 0.72,
    cooldown_sec: float = 3600.0,
) -> List[Dict[str, Any]]:
    """
    Check incoming message embedding against load-bearing anchors.
    Returns list of conflict warnings. Empty list = no conflicts.
    Zero extra ONNX calls — reuses Observer step 1 embedding.
    """
    now = time.time()
    warnings = []

    for anchor in ctx.anchor_index.anchors.values():
        # Filter: only load-bearing types
        if anchor.anchor_type not in GUARDIAN_TYPES:
            continue
        # Filter: decayed decisions skipped
        if anchor.anchor_type == "decision" and anchor.decay_level > 0:
            continue
        # Filter: no embedding → skip
        if anchor.embedding is None:
            continue
        # Cooldown: skip if warned recently
        last_warned = ctx.recently_warned.get(anchor.anchor_id, 0)
        if now - last_warned < cooldown_sec:
            continue

        sim = float(np.dot(embedding, anchor.embedding))
        if sim >= threshold:
            warnings.append({
                "anchor_id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "set_at": anchor.created_at,
                "similarity": round(sim, 3),
                "decay_level": anchor.decay_level,
            })
            ctx.recently_warned[anchor.anchor_id] = now

    warnings.sort(key=lambda x: x["similarity"], reverse=True)
    return warnings
```

---

## 5. Observer Pipeline Integration

**File:** `src/mnemostroma/observer/pipeline.py`

Step 1.5 handles both Guardian and Surfacing in one pass:

```python
# Step 1.5 [NEW]: Anchor Guardian + Associative Surfacing (shared embedding pass)
if embedding is not None and (
    ctx.config.anchor_guardian.enabled
    or ctx.config.associative_surfacing.enabled
):
    from ..subconscious.guardian import anchor_guardian
    from ..subconscious.surfacing import associative_scan

    # Run in parallel — both use same embedding, independent results
    guardian_task = asyncio.create_task(
        anchor_guardian(embedding, ctx,
                        threshold=ctx.config.anchor_guardian.threshold,
                        cooldown_sec=ctx.config.anchor_guardian.cooldown_sec)
    ) if ctx.config.anchor_guardian.enabled else None

    surfacing_task = asyncio.create_task(
        associative_scan(embedding, ctx,
                         anchor_threshold=ctx.config.associative_surfacing.anchor_threshold,
                         session_threshold=ctx.config.associative_surfacing.session_threshold,
                         max_results=ctx.config.associative_surfacing.max_results)
    ) if ctx.config.associative_surfacing.enabled else None

    results = await asyncio.gather(
        guardian_task or asyncio.sleep(0),
        surfacing_task or asyncio.sleep(0),
        return_exceptions=True
    )

    if guardian_task and not isinstance(results[0], Exception):
        ctx.conflict_warnings.extend(results[0])

    if surfacing_task and not isinstance(results[1], Exception):
        ctx.surfaced_queue.extend(results[1])
```

---

## 6. SystemContext Changes

**File:** `src/mnemostroma/core.py`

Add to `SystemContext` (shared with Spec 11.A):
```python
conflict_warnings: List[Dict[str, Any]] = field(default_factory=list)
recently_warned: Dict[str, float] = field(default_factory=dict)  # anchor_id → timestamp
```

`recently_warned` persists across ctx_active() calls — intentional. Cleared only on daemon restart or explicit flush.

---

## 7. ctx_active() Changes

**File:** `src/mnemostroma/tools/read.py`

```python
async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    result = { ...existing fields... }

    # Anchor Guardian — Layer 1: keyword pre-check (sync, immediate)
    keyword_warnings = []
    if ctx.config.anchor_guardian.enabled and ctx.last_message_text:
        keyword_warnings = _keyword_anchor_check(ctx.last_message_text, ctx)

    # Anchor Guardian — Layer 2: async results from Observer pipeline
    async_warnings = list(ctx.conflict_warnings)
    ctx.conflict_warnings.clear()

    all_warnings = _merge_warnings(keyword_warnings, async_warnings)
    if all_warnings:
        result["conflict_warnings"] = all_warnings

    # Surfacing (Spec 11.A)
    surfaced = list(ctx.surfaced_queue)
    ctx.surfaced_queue.clear()
    if surfaced:
        result["surfaced"] = surfaced

    return result


def _keyword_anchor_check(text: str, ctx: SystemContext) -> List[Dict]:
    """Layer 1: fast keyword match. Catches obvious conflicts same-turn."""
    text_lower = text.lower()
    hits = []
    now = time.time()
    cooldown = ctx.config.anchor_guardian.cooldown_sec

    for anchor in ctx.anchor_index.anchors.values():
        if anchor.anchor_type not in GUARDIAN_TYPES:
            continue
        last_warned = ctx.recently_warned.get(anchor.anchor_id, 0)
        if now - last_warned < cooldown:
            continue
        words = [w for w in anchor.brief.lower().split() if len(w) > 4]
        if any(w in text_lower for w in words):
            hits.append({
                "anchor_id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": None,
                "layer": 1,
                "set_at": anchor.created_at,
            })
    return hits[:3]
```

---

## 8. ctx_active() Response Format

```json
{
  "intent_summary": "...",
  "active_variables": [...],
  "last_decisions": [...],
  "conflict_warnings": [
    {
      "anchor_id": "sess_abc123",
      "brief": "No Redis in Core — use SQLite or in-process solutions only",
      "anchor_type": "constraint",
      "set_at": 1743800000,
      "similarity": 0.84,
      "decay_level": 0,
      "layer": 2
    }
  ],
  "surfaced": [...]
}
```

`conflict_warnings` is absent if empty (not `[]`). Agent sees it only when relevant.

`similarity: null` for Layer 1 (keyword match). Agent can use this to gauge confidence.

---

## 9. Cooldown Logic

Prevents warning fatigue — same anchor not surfaced more than once per hour by default.

```
First time anchor X triggers: warn → recently_warned[X] = now
Next message, same anchor: now - recently_warned[X] < 3600 → skip
After 1 hour: fires again if still triggered
```

`recently_warned` is in-memory only. Clears on daemon restart. Not persisted to SQLite (intentional — warning fatigue resets on fresh start).

---

## 10. Known Issues / Open Questions

| Issue | Severity | Resolution |
|---|---|---|
| One-turn lag for Layer 2 (same as Spec 11.A) | Medium | Layer 1 covers same turn |
| Shared scan with Surfacing: both run on same embedding | Low | asyncio.gather(), no blocking |
| Threshold 0.72 may be too low for some domains | Medium | Configurable, monitor false positive rate in logs |
| `recently_warned` grows unbounded over long daemon lifetime | Low | Cap at 1000 entries, evict oldest |
| Anchor has no embedding if created before v1.7 | Medium | Guard: `if anchor.embedding is None: skip` |
| Layer 1 keyword match too noisy for short anchor briefs | Medium | Require word length > 4 chars |

---

## 11. Tests Required

- `test_anchor_guardian_fires_on_conflict()` — incoming matches constraint → warning returned
- `test_anchor_guardian_respects_cooldown()` — same anchor, second call within 1h → no warning
- `test_anchor_guardian_skips_milestone()` — milestone anchor → never triggers
- `test_anchor_guardian_skips_decayed_decision()` — decay_level > 0 decision → skipped
- `test_anchor_guardian_threshold()` — similarity 0.71 → no warning; 0.73 → warning
- `test_keyword_check_layer1_same_turn()` — keyword in message → immediate warning in ctx_active
- `test_conflict_warnings_cleared_after_ctx_active()` — ctx.conflict_warnings empty after read
- `test_guardian_and_surfacing_parallel()` — both run without blocking each other
- `test_conflict_warnings_absent_if_empty()` — no warnings → key not in response dict

---

## 12. Config

```json
"anchor_guardian": {
    "enabled": true,
    "threshold": 0.72,
    "cooldown_sec": 3600,
    "guardian_types": ["principle", "constraint", "critical", "decision"]
}
```
