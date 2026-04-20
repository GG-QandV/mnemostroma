# Spec: Associative Surfacing v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.A
> Depends on: Observer pipeline (pipeline.py), AnchorIndex, SystemContext, ctx_active()

---

## 1. Overview

Human memory surfaces related context involuntarily when a trigger pattern appears — without an explicit search query. This spec defines the same mechanism for Mnemostroma: incoming messages automatically trigger related memories to surface into `ctx_active()` output, without agent tool calls.

**Key principle:** Agent calls nothing. System surfaces. Observer triggers. ctx_active() delivers.

---

## 2. Architecture

```
Incoming message
      │
Observer pipeline Step 1: embed(message) → embedding_vec  [already exists]
      │
      ├─→ Step 1.5 [NEW]: associative_scan(embedding_vec, ctx)
      │         │
      │         ├─→ scan AnchorIndex (cosine, threshold 0.75+)
      │         ├─→ scan RAM SessionIndex (cosine, threshold 0.78+)
      │         ├─→ deduplicate with current ctx_active content
      │         ├─→ limit to max_surfaced (default: 3)
      │         └─→ write → ctx.surfaced_queue
      │
      └─→ Step 2+: existing pipeline continues unchanged
      
ctx_active() [called by agent]:
      │
      ├─→ reads ctx.surfaced_queue
      ├─→ appends to response as "surfaced" field
      └─→ clears ctx.surfaced_queue
```

---

## 3. Two-Layer Design (Race Condition Mitigation)

Observer is async. When agent calls `ctx_active()` after receiving message N, Observer is still processing message N-1. Surfacing based on message N won't be ready yet.

Solution: two layers operating at different speeds.

```
Layer 1 — Synchronous keyword pre-check (inside ctx_active(), <1ms)
  Input:  last raw message text (stored as ctx.last_message_text)
  Method: keyword/regex match against anchor brief strings
  Output: immediate rough surfacing (false positives acceptable)
  Fires:  now, same turn

Layer 2 — Async semantic scan (inside Observer pipeline step 1.5, ~3ms)
  Input:  embedding vector from step 1
  Method: cosine scan of AnchorIndex + SessionIndex
  Output: precise surfacing stored in ctx.surfaced_queue
  Fires:  next turn (one turn behind, but accurate)
```

Both results merged in ctx_active() response. Layer 1 catches obvious triggers immediately. Layer 2 corrects and enriches next turn.

---

## 4. associative_scan() — New Module

**Location:** `src/mnemostroma/subconscious/surfacing.py` (new file)

```python
async def associative_scan(
    embedding: np.ndarray,
    ctx: SystemContext,
    anchor_threshold: float = 0.75,
    session_threshold: float = 0.78,
    max_results: int = 3,
) -> List[Dict[str, Any]]:
    """
    Scan anchor and session indices for associatively related items.
    Reuses pre-computed embedding — zero extra ONNX calls.
    Returns list of surfaced items sorted by similarity desc.
    """
    results = []

    # 1. Scan AnchorIndex
    for anchor in ctx.anchor_index.anchors.values():
        if anchor.embedding is None:
            continue
        sim = float(np.dot(embedding, anchor.embedding))
        if sim >= anchor_threshold:
            results.append({
                "type": "anchor",
                "id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": round(sim, 3),
                "decay_level": anchor.decay_level,
            })

    # 2. Scan SessionIndex (RAM only)
    for sb in ctx.ram_index.values():
        if sb.embedding is None:
            continue
        sim = float(np.dot(embedding, sb.embedding))
        if sim >= session_threshold:
            results.append({
                "type": "session",
                "id": sb.session_id,
                "brief": sb.brief,
                "importance": sb.importance,
                "similarity": round(sim, 3),
                "created_at": sb.created_at,
            })

    # 3. Sort, deduplicate, limit
    results.sort(key=lambda x: x["similarity"], reverse=True)
    seen = set()
    deduped = []
    for r in results:
        if r["id"] not in seen:
            seen.add(r["id"])
            deduped.append(r)
    
    return deduped[:max_results]
```

---

## 5. Observer Pipeline Integration

**File:** `src/mnemostroma/observer/pipeline.py`

Insert after Step 1 (embed), before Step 2 (Marker):

```python
# Step 1.5 [NEW]: Associative surfacing
if ctx.config.associative_surfacing.enabled and embedding is not None:
    from ..subconscious.surfacing import associative_scan
    surfaced = await associative_scan(
        embedding,
        ctx,
        anchor_threshold=ctx.config.associative_surfacing.anchor_threshold,
        session_threshold=ctx.config.associative_surfacing.session_threshold,
        max_results=ctx.config.associative_surfacing.max_results,
    )
    if surfaced:
        ctx.surfaced_queue.extend(surfaced)
```

---

## 6. SystemContext Changes

**File:** `src/mnemostroma/core.py`

Add to `SystemContext`:
```python
surfaced_queue: List[Dict[str, Any]] = field(default_factory=list)
last_message_text: str = ""  # for Layer 1 keyword pre-check
```

---

## 7. ctx_active() Changes

**File:** `src/mnemostroma/tools/read.py` (or admin.py — wherever ctx_active lives)

```python
async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    result = { ...existing fields... }

    # Layer 1: keyword pre-check (sync, immediate)
    surfaced_layer1 = []
    if ctx.config.associative_surfacing.enabled and ctx.last_message_text:
        surfaced_layer1 = _keyword_surface(ctx.last_message_text, ctx)

    # Layer 2: async results from Observer
    surfaced_layer2 = list(ctx.surfaced_queue)
    ctx.surfaced_queue.clear()

    # Merge, deduplicate
    all_surfaced = _merge_surfaced(surfaced_layer1, surfaced_layer2)
    if all_surfaced:
        result["surfaced"] = all_surfaced

    return result


def _keyword_surface(text: str, ctx: SystemContext) -> List[Dict]:
    """Fast keyword match of anchor briefs against incoming text. Layer 1."""
    text_lower = text.lower()
    hits = []
    for anchor in ctx.anchor_index.anchors.values():
        if anchor.anchor_type not in ("constraint", "principle", "decision"):
            continue
        words = [w for w in anchor.brief.lower().split() if len(w) > 4]
        if any(w in text_lower for w in words):
            hits.append({
                "type": "anchor",
                "id": anchor.anchor_id,
                "brief": anchor.brief,
                "anchor_type": anchor.anchor_type,
                "similarity": None,  # keyword match, no score
                "layer": 1,
            })
    return hits[:3]
```

---

## 8. Config

```json
"associative_surfacing": {
    "enabled": true,
    "anchor_threshold": 0.75,
    "session_threshold": 0.78,
    "max_results": 3
}
```

---

## 9. Known Issues / Open Questions

| Issue | Severity | Resolution |
|---|---|---|
| One-turn lag for Layer 2 | Medium | Accepted — Layer 1 covers same turn |
| Overlap with Workflow 3 (anchor scan) | Medium | Share single scan pass, split by threshold |
| Noise if threshold too low | High | Default 0.75+, configurable, monitor in logs |
| Embedding not always available (pre-embed fail) | Medium | Guard: `if embedding is not None` |
| surfaced_queue grows if ctx_active() not called | Low | Max cap: clear if len > 20 |

---

## 10. Tests Required

- `test_associative_scan_returns_relevant()` — known embedding, known anchor → hit
- `test_associative_scan_threshold_filtering()` — low similarity → no result
- `test_associative_scan_max_results()` — 10 matches → returns 3
- `test_keyword_surface_layer1()` — keyword in message → anchor surfaced immediately
- `test_surfaced_queue_cleared_after_ctx_active()` — queue empty after read
- `test_surfaced_dedup_with_existing_context()` — already in ctx_active → not duplicated
