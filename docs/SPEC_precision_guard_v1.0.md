# Spec: Precision Guard v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.D
> Depends on: PRECISION_PATTERNS (observer/filter.py), precision_log (SQLite), SystemContext, ctx_active()

---

## 1. Overview

Agent text contains URLs, version numbers, and metrics. These can drift: agent mentions `v2.1` when the last recorded version was `v2.0`, or references a different API endpoint than the one stored. Neither Guardian nor Surfacing catches this — they work on semantic similarity, not value-level comparison.

**Precision Guard** extracts precision artifacts from the current agent output and compares them against the RAM-cached precision_log. On discrepancy → `precision_warnings` field appears in `ctx_active()` next turn.

**Key principle:** Pure regex extraction. No ONNX call. RAM-first lookup. One-turn lag (same pattern as Guardian/Surfacing).

---

## 2. What It Checks

| Type | Pattern (from filter.py) | Discrepancy definition |
|---|---|---|
| `link` | `https?://[^\s]+` | Same domain, different URL under same context |
| `version` | `v?\d+\.\d+(?:\.\d+)?` | Same major version group, different string |
| `number` | `\d+[.,]?\d*\s*(MB\|GB\|ms\|%…)` | Same unit+context, different value |

Types `email`, `phone`, `hash`, `error` — not checked (low discrepancy risk).

---

## 3. Architecture

```
Observer Step 0.5 [NEW] — sync, before embed, <1ms:
      │
      ├─→ precision_extract(text) → [{type, value, raw}]
      │         Uses PRECISION_PATTERNS from filter.py (reuse, no duplication)
      │
      ├─→ for each artifact:
      │       ctx_tag = _derive_context_tag(artifact, text)  # heuristic, see §4.2
      │       key = (type, ctx_tag)
      │       stored = ctx.precision_ram.get(key)
      │       if stored and not _same_value(artifact.value, stored["value"], artifact.type):
      │           ctx.precision_warnings.append(warning)
      │
      └─→ (update precision_ram happens AFTER pipeline completes, in Step 8 hook)

ctx_active() [consumer]:
      ├─→ warnings = list(ctx.precision_warnings)
      ├─→ ctx.precision_warnings.clear()
      └─→ if warnings: result["precision_warnings"] = warnings
```

### 3.1 Why Step 0.5 (not Step 1.5)

Step 1.5 runs async alongside Guardian/Surfacing and needs embedding. Precision Guard needs no embedding — pure regex. Running at Step 0.5 (sync, before embed):
- Zero added latency to embed/NER path
- Simpler code path
- If pre-filter rejects at Step 0 → Step 0.5 also skipped (guard: `if not structural_prefilter(text): return`)

---

## 4. New Module

**Location:** `src/mnemostroma/subconscious/precision_guard.py` (new file)

### 4.1 Extraction

```python
import re
from typing import List, Dict, Any, Optional
from ..observer.filter import PRECISION_PATTERNS

_COMPILED = {
    name: re.compile(pattern)
    for name, pattern in PRECISION_PATTERNS.items()
    if name in ("link", "version", "number")
}

def precision_extract(text: str) -> List[Dict[str, Any]]:
    """Extract precision artifacts from text. Returns list of {type, value, raw}."""
    results = []
    for ptype, pattern in _COMPILED.items():
        for match in pattern.finditer(text):
            results.append({
                "type": ptype,
                "value": match.group(0).strip(),
                "raw": match.group(0),
            })
    return results
```

### 4.2 Context Tag Derivation

```python
def _derive_context_tag(artifact: Dict, text: str) -> str:
    """Heuristic: extract 1-2 word context around the artifact."""
    value = artifact["value"]
    idx = text.find(value)
    if idx == -1:
        return "unknown"
    # Take up to 30 chars before the artifact, extract last meaningful word
    prefix = text[max(0, idx - 40):idx].strip()
    words = [w for w in prefix.split() if len(w) > 3 and w.isalpha()]
    return words[-1].lower() if words else "unknown"
```

### 4.3 Value Comparison

```python
def _same_value(a: str, b: str, ptype: str) -> bool:
    """True if a and b are considered the same value for the given type."""
    if ptype == "link":
        from urllib.parse import urlparse
        pa, pb = urlparse(a), urlparse(b)
        # Same netloc + path → same. Different path under same domain → mismatch.
        return pa.netloc == pb.netloc and pa.path == pb.path
    if ptype == "version":
        # Strip leading 'v', compare full string
        return a.lstrip("vV") == b.lstrip("vV")
    if ptype == "number":
        # Compare numeric part only (ignore trailing spaces)
        import re as _re
        na = _re.search(r"[\d.,]+", a)
        nb = _re.search(r"[\d.,]+", b)
        if na and nb:
            return na.group(0).replace(",", ".") == nb.group(0).replace(",", ".")
    return a == b
```

### 4.4 Guard Main Function

```python
def precision_guard(text: str, ctx: "SystemContext") -> None:
    """
    Extract precision artifacts from text, compare with precision_ram.
    Appends warnings to ctx.precision_warnings in-place.
    Called synchronously at Observer Step 0.5.
    """
    artifacts = precision_extract(text)
    for artifact in artifacts:
        ctx_tag = _derive_context_tag(artifact, text)
        key = (artifact["type"], ctx_tag)
        stored = ctx.precision_ram.get(key)
        if stored and not _same_value(artifact["value"], stored["value"], artifact["type"]):
            ctx.precision_warnings.append({
                "type": artifact["type"],
                "current_value": artifact["value"],
                "stored_value": stored["value"],
                "context_tag": ctx_tag,
                "stored_at": stored.get("stored_at", 0),
                "note": f"{artifact['type']} changed since last recorded",
            })
```

---

## 5. Observer Pipeline Integration

**File:** `src/mnemostroma/observer/pipeline.py`

Insert at Step 0.5 (after pre-filter Step 0, before embed Step 1):

```python
# Step 0.5 [NEW]: Precision Guard — sync, no ONNX
if ctx.config.precision_guard.enabled:
    from ..subconscious.precision_guard import precision_guard
    precision_guard(stripped, ctx)
```

Precision RAM update (write path) — at Step 8, after SessionBrief is created with tags:

```python
# Step 8.5 [NEW]: Update precision_ram with artifacts from this session
if ctx.config.precision_guard.enabled and sb:
    from ..subconscious.precision_guard import precision_extract, _derive_context_tag
    now = int(time.time())
    for artifact in precision_extract(stripped):
        ctx_tag = _derive_context_tag(artifact, stripped)
        key = (artifact["type"], ctx_tag)
        ctx.precision_ram[key] = {
            "value": artifact["value"],
            "session_id": session_id,
            "stored_at": now,
        }
    # Cap RAM size
    if len(ctx.precision_ram) > 1000:
        oldest_key = min(ctx.precision_ram, key=lambda k: ctx.precision_ram[k].get("stored_at", 0))
        del ctx.precision_ram[oldest_key]
```

---

## 6. Conductor Startup — Preload precision_ram

**File:** `src/mnemostroma/conductor.py` (in `start()`)

```python
# Preload precision_ram from precision_log (recent N entries only)
if config.precision_guard.enabled:
    from .subconscious.precision_guard import _derive_context_tag
    async with db.execute(
        """SELECT type, value, context_tag, created_at
           FROM precision_log ORDER BY created_at DESC LIMIT 500"""
    ) as cur:
        rows = await cur.fetchall()
    for ptype, value, ctx_tag, created_at in rows:
        if ptype in ("link", "version", "number"):
            key = (ptype, ctx_tag or "unknown")
            if key not in ctx.precision_ram:  # newest wins (DESC order)
                ctx.precision_ram[key] = {
                    "value": value,
                    "stored_at": created_at,
                }
```

---

## 7. SystemContext Changes

**File:** `src/mnemostroma/core.py`

```python
precision_warnings: List[Dict[str, Any]] = field(default_factory=list)
precision_ram: Dict[tuple, Dict[str, Any]] = field(default_factory=dict)
# key: (type, context_tag) → {value, session_id, stored_at}
# Populated at Conductor startup from precision_log + updated per Observer run.
```

---

## 8. ctx_active() Changes

**File:** `src/mnemostroma/tools/read.py`

```python
async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    result = { ...existing fields... }

    # Precision Guard
    precision_warns = list(ctx.precision_warnings)
    ctx.precision_warnings.clear()
    if precision_warns:
        result["precision_warnings"] = precision_warns

    return result
```

---

## 9. Response Format

```json
{
  "precision_warnings": [
    {
      "type": "link",
      "current_value": "https://api.example.com/v2/sessions",
      "stored_value": "https://api.example.com/v1/sessions",
      "context_tag": "sessions",
      "stored_at": 1744100000,
      "note": "link changed since last recorded"
    },
    {
      "type": "version",
      "current_value": "v2.1.0",
      "stored_value": "v2.0.3",
      "context_tag": "mnemostroma",
      "stored_at": 1744050000,
      "note": "version changed since last recorded"
    }
  ]
}
```

`precision_warnings` absent if no discrepancies detected.

---

## 10. Config

```json
"precision_guard": {
    "enabled": true,
    "check_types": ["link", "version", "number"],
    "ram_cap": 1000
}
```

---

## 11. Known Issues

| Issue | Severity | Resolution |
|---|---|---|
| Context tag heuristic is approximate | Medium | Acceptable for Phase 1 — catches majority of cases |
| precision_ram loses state on daemon restart | Low | Preloaded from precision_log at startup |
| False positives: version bump in changelog context | Medium | Only fires when context_tag matches; low noise in practice |
| One-turn lag (Step 0.5 fires, ctx_active reads next call) | Medium | Accepted — same as Guardian/Surfacing |
| precision_ram can hold stale entries indefinitely | Low | Cap at 1000, evict oldest by stored_at |
| number comparison: "600 MB" vs "600MB" → same | Low | Strip whitespace before compare |

---

## 12. Tests Required

- `test_precision_guard_link_mismatch()` — different URL same domain+context → warning
- `test_precision_guard_link_same()` — identical URL → no warning
- `test_precision_guard_version_mismatch()` — v2.0.3 → v2.1.0, same context → warning
- `test_precision_guard_no_stored()` — first occurrence → no warning (nothing to compare)
- `test_precision_guard_cleared_after_ctx_active()` — ctx.precision_warnings empty after read
- `test_precision_guard_ram_cap()` — 1001 entries → oldest evicted
- `test_precision_ram_preload()` — startup loads recent precision_log entries into RAM
- `test_precision_guard_disabled()` — `enabled: false` → Step 0.5 skipped
