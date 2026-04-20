# Spec: Urgency Pulse v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.F
> Depends on: urgency_index (Observer Step 7b), ctx_active(), SystemContext

---

## 1. Overview

`urgency_active` already exists in `ctx_active()` — it returns all active deadlines on every call. The problem: agent sees the same urgency data every turn → noise, ignored.

**Urgency Pulse** adds escalation tracking: signal fires **only when urgency level changes** (new item or level increase). Agent attention is drawn exactly when anxiety should increase.

**Key principle:** No new Observer step. No new MCP tool. Thin layer inside `ctx_active()` operating on already-populated `urgency_index`.

---

## 2. Level Definitions

```python
URGENCY_LEVELS = {
    "overdue":  lambda h: h <= 0,
    "critical": lambda h: 0 < h <= 6,
    "high":     lambda h: 6 < h <= 24,
    "medium":   lambda h: 24 < h <= 72,
    "low":      lambda h: h > 72,
}

LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3, "overdue": 4}

def compute_urgency_level(deadline_ts: float) -> str:
    hours_left = (deadline_ts - time.time()) / 3600
    for level, check in URGENCY_LEVELS.items():
        if check(hours_left):
            return level
    return "low"
```

---

## 3. Architecture

```
ctx_active() called by agent
      │
      ├─→ read ctx.urgency_index (RAM, already populated by Observer Step 7b)
      │
      ├─→ for each item in urgency_index:
      │       if item["expired"]: skip
      │       hours_left = (item["deadline_ts"] - now) / 3600
      │       level = compute_urgency_level(item["deadline_ts"])
      │       old_level = ctx.urgency_level_cache.get(session_id)
      │
      │       if old_level is None (new item):
      │           → emit pulse (is_new=True)
      │       elif LEVEL_ORDER[level] > LEVEL_ORDER[old_level]:
      │           → emit pulse (escalation)
      │
      │       ctx.urgency_level_cache[session_id] = level
      │
      ├─→ if pulse_list non-empty: result["urgency_pulse"] = pulse_list
      │
      └─→ cleanup: remove from cache session_ids no longer in urgency_index
```

**Note:** `urgency_active` field remains unchanged — always present, full list. `urgency_pulse` is the new signal, absent if no change.

---

## 4. Implementation — ctx_active() Changes

**File:** `src/mnemostroma/tools/read.py`

```python
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3, "overdue": 4}

def _compute_urgency_level(deadline_ts: float) -> str:
    hours_left = (deadline_ts - time.time()) / 3600
    if hours_left <= 0:
        return "overdue"
    if hours_left <= 6:
        return "critical"
    if hours_left <= 24:
        return "high"
    if hours_left <= 72:
        return "medium"
    return "low"


def _urgency_pulse(ctx: SystemContext) -> List[Dict[str, Any]]:
    """Compute urgency escalation events. Returns list of new/escalated items."""
    now = time.time()
    pulse = []
    active_ids = set()

    for session_id, item in ctx.urgency_index.items():
        if item.get("expired"):
            continue
        deadline_ts = item.get("deadline_ts")
        if not deadline_ts:
            continue

        active_ids.add(session_id)
        level = _compute_urgency_level(deadline_ts)
        old_level = ctx.urgency_level_cache.get(session_id)
        hours_left = (deadline_ts - now) / 3600

        is_new = old_level is None
        is_escalated = (
            not is_new
            and LEVEL_ORDER.get(level, 0) > LEVEL_ORDER.get(old_level, 0)
        )

        if is_new or is_escalated:
            pulse.append({
                "session_id": session_id,
                "brief": item.get("value", ""),
                "level": level,
                "prev_level": old_level,
                "hours_left": round(hours_left, 1),
                "deadline_ts": deadline_ts,
                "is_new": is_new,
            })

        ctx.urgency_level_cache[session_id] = level

    # Cleanup stale cache entries (session evicted from urgency_index)
    stale = [sid for sid in ctx.urgency_level_cache if sid not in active_ids]
    for sid in stale:
        del ctx.urgency_level_cache[sid]

    return pulse


async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    # ...existing code...

    # Urgency Pulse — escalation events only
    pulse = _urgency_pulse(ctx)
    if pulse:
        res["urgency_pulse"] = pulse

    # ...rest of existing code...
```

---

## 5. SystemContext Changes

**File:** `src/mnemostroma/core.py`

```python
urgency_level_cache: Dict[str, str] = field(default_factory=dict)
# session_id → last known level ("low" | "medium" | "high" | "critical" | "overdue")
# Clears on daemon restart — intentional, all active deadlines appear as "new" once.
```

---

## 6. Response Format

```json
{
  "urgency_active": [...],
  "urgency_pulse": [
    {
      "session_id": "sess_abc123",
      "brief": "Deploy before 18:00 today",
      "level": "critical",
      "prev_level": "high",
      "hours_left": 2.3,
      "deadline_ts": 1744210000,
      "is_new": false
    }
  ]
}
```

`urgency_pulse` absent if no escalation this turn.  
`is_new: true` means first time this urgency item is seen (daemon restart or new deadline).

---

## 7. Config

```json
"urgency_pulse": {
    "enabled": true
}
```

No threshold config needed — level boundaries are fixed business logic.

---

## 8. Known Issues

| Issue | Severity | Resolution |
|---|---|---|
| Daemon restart → all active deadlines fire as `is_new=True` | Low | Acceptable — better missed by cache reset than never seen |
| `urgency_level_cache` grows during long daemon lifetime | Low | Cleanup on each ctx_active() call (stale removal) |
| deadline_ts=None for deadline_w (weekly) urgency | Medium | Guard: `if not deadline_ts: skip` |
| hours_left computation: urgency_index stores stale hours_left | Medium | Always recompute from deadline_ts, never use stored hours_left |

---

## 9. Tests Required

- `test_urgency_pulse_new_item()` — first call with active deadline → `is_new=True` in pulse
- `test_urgency_pulse_no_change()` — same level twice → `urgency_pulse` absent second call
- `test_urgency_pulse_escalation()` — level was "medium", now "high" → pulse fires
- `test_urgency_pulse_downgrade_ignored()` — level decrease (overdue→high impossible, but test handles gracefully) → no pulse
- `test_urgency_pulse_expired_skipped()` — `expired=True` item → never in pulse
- `test_urgency_level_cache_cleanup()` — session removed from urgency_index → removed from cache
- `test_compute_urgency_level_boundaries()` — 0h=overdue, 5h=critical, 23h=high, 71h=medium, 73h=low
