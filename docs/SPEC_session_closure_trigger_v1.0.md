# Spec: Session Closure Trigger v1.0

> Status: Draft | Date: 2026-04-09
> Phase: 11.G
> Depends on: ctx_bridge() (tools/admin.py), last_message_text (SystemContext, Phase 11.A), ctx_active()

---

## 1. Overview

When a user says "thanks, that's all for today" or "see you tomorrow", a human collaborator instinctively summarizes: "right, so the key decisions were X and Y, and we left Z open." Mnemostroma should do the same.

**Session Closure Trigger** detects farewell patterns in the user's last message and automatically generates a `ctx_bridge()` handoff packet, delivered via `ctx_active()` in the same turn — no agent tool call required.

**Key principle:** No Observer step needed. Farewell comes from the USER, not the agent. User input is already stored in `ctx.last_message_text` (Phase 11.A). Detection happens synchronously in `ctx_active()` Layer 1.

---

## 2. Architecture

```
User sends farewell message
      │
Observer: stores text in ctx.last_message_text  [Phase 11.A]
      │
Agent calls ctx_active()
      │
      ├─→ Layer 1 (sync, <0.5ms):
      │       _farewell_check(ctx.last_message_text)
      │           │
      │           ├─→ FAREWELL_PATTERNS regex match
      │           ├─→ cooldown check: now > ctx.closure_cooldown_until
      │           ├─→ match + not in cooldown:
      │           │       bridge = await ctx_bridge(ctx)
      │           │       result["session_closure"] = {
      │           │           "trigger": "farewell_detected",
      │           │           "bridge": bridge,
      │           │       }
      │           │       ctx.closure_cooldown_until = now + cooldown_sec
      │           └─→ no match or in cooldown: skip
      │
      └─→ return result
```

**No one-turn lag.** Same-turn delivery — farewell detection is sync, `ctx_bridge()` reads RAM only.

---

## 3. Farewell Patterns

```python
import re

FAREWELL_PATTERNS = [
    # Russian
    re.compile(
        r"\b(пока|до\s+свидания|до\s+встречи|на\s+сегодня\s+всё|закончили|"
        r"завершаем|на\s+этом\s+всё|спасибо\s+за\s+работу|достаточно\s+на\s+сегодня|"
        r"завтра\s+продолжим|до\s+завтра|закрываем)\b",
        re.IGNORECASE
    ),
    # English
    re.compile(
        r"\b(goodbye|bye|see\s+you|that'?s?\s+all\s+for\s+today|done\s+for\s+today|"
        r"closing\s+(up|out|session)?|signing\s+off|wrapping\s+up|"
        r"till\s+next\s+time|until\s+next\s+time|thanks,?\s+done|"
        r"that'?s?\s+it\s+for\s+today|end\s+session|good\s+night)\b",
        re.IGNORECASE
    ),
]

def _is_farewell(text: str) -> bool:
    """True if text contains a farewell pattern. Requires word len > 3 to avoid noise."""
    text = text.strip()
    if len(text) < 4:
        return False
    return any(p.search(text) for p in FAREWELL_PATTERNS)
```

**Noise guard:** Patterns require specific multi-word phrases or unambiguous farewell words. Single "ok" or "good" do not match.

---

## 4. Implementation — ctx_active() Changes

**File:** `src/mnemostroma/tools/read.py`

```python
from .admin import ctx_bridge as _ctx_bridge


async def ctx_active(ctx: SystemContext) -> Dict[str, Any]:
    result = { ...existing fields... }

    # Session Closure Trigger — Layer 1 (sync farewell check on user's last message)
    if ctx.config.session_closure.enabled and ctx.last_message_text:
        now = time.time()
        if (
            _is_farewell(ctx.last_message_text)
            and now > ctx.closure_cooldown_until
        ):
            bridge = await _ctx_bridge(ctx)
            result["session_closure"] = {
                "trigger": "farewell_detected",
                "bridge": bridge,
            }
            ctx.closure_cooldown_until = now + ctx.config.session_closure.cooldown_sec

    return result
```

---

## 5. ctx_bridge() — No Changes Required

`ctx_bridge()` in `tools/admin.py` already returns everything needed:

```python
{
    "intent_summary": str,
    "active_variables": List[str],   # critical/principle sessions
    "last_decisions": List[str],     # critical/important sessions
    "open_issues": List[str],        # conflict_flag sessions
    "urgency_active": List[Dict],    # active deadlines
    "ram_sessions": int,             # total sessions in RAM
}
```

Session Closure Trigger reuses it as-is. No modification to admin.py.

---

## 6. SystemContext Changes

**File:** `src/mnemostroma/core.py`

```python
closure_cooldown_until: float = 0.0
# Unix timestamp — closure trigger suppressed until this time.
# Prevents re-firing on follow-up messages after farewell.
# Resets on daemon restart (intentional).
```

Note: `last_message_text` is already added by Phase 11.A.

---

## 7. Response Format

```json
{
  "intent_summary": "...",
  "active_variables": [...],
  "session_closure": {
    "trigger": "farewell_detected",
    "bridge": {
      "intent_summary": "Refactoring Observer pipeline for Phase 11",
      "active_variables": [
        "[critical] No Redis in Core — SQLite or in-process only",
        "[principle] All signals delivered via ctx_active(), no polling"
      ],
      "last_decisions": [
        "Unified anchor scan pass for Guardian + Surfacing + Open Loop",
        "precision_ram_index in RAM, preloaded from precision_log on startup"
      ],
      "open_issues": [
        "strip_logs_v2.py sync to Repo C — pending review"
      ],
      "urgency_active": [],
      "ram_sessions": 18
    }
  }
}
```

`session_closure` absent if no farewell detected or cooldown active.

---

## 8. Cooldown Logic

```
User says "bye" at T=0:
    → _is_farewell() matches
    → bridge generated
    → closure_cooldown_until = T + 1800

User sends follow-up "wait, one more thing" at T=30:
    → last_message_text = "wait, one more thing"
    → _is_farewell() → False (no farewell word) → skip

User says "ok bye for real" at T=60:
    → _is_farewell() → True
    → now (T+60) < closure_cooldown_until (T+1800) → suppressed

After T=1800:
    → cooldown expired → fires again if farewell pattern present
```

**Default cooldown:** `1800s` (30 minutes). Long enough to survive "wait, one more thing" patterns; short enough to fire again if user genuinely reconnects within the same daemon session.

---

## 9. Interaction with ctx_bridge (button)

Agent can still call `ctx_bridge()` explicitly at any time. Session Closure Trigger auto-calls the same function on farewell detection. No conflict:
- Both return identical structure
- Closure Trigger delivers the packet as `session_closure.bridge` inside ctx_active() response
- Explicit `ctx_bridge()` call returns the packet directly

---

## 10. Config

```json
"session_closure": {
    "enabled": true,
    "cooldown_sec": 1800
}
```

---

## 11. Known Issues

| Issue | Severity | Resolution |
|---|---|---|
| Agent farewells not detected (Observer processes agent output, not user input) | Low | Intentional — `last_message_text` is user message only |
| Short user message "bye" matches but has no context | Low | Bridge still correct — reflects current RAM state |
| Daemon restart resets `closure_cooldown_until` → refires next session | Low | Acceptable — cooldown is within-session concept |
| User types a quoted farewell: `he said "goodbye"` | Low | Rare; false positive acceptable, bridge is always safe to deliver |
| ctx_bridge() writes to log_event (async) — nested inside ctx_active() | Low | Both are async, no issue; log_event is non-blocking |

---

## 12. Tests Required

- `test_closure_fires_on_farewell_en()` — "that's all for today" → `session_closure` in response
- `test_closure_fires_on_farewell_ru()` — "на сегодня всё" → `session_closure` in response
- `test_closure_absent_on_normal_message()` — "can you check the logs?" → no `session_closure`
- `test_closure_respects_cooldown()` — second farewell within 1800s → suppressed
- `test_closure_after_cooldown_fires_again()` — farewell at T=0, T=1801 → fires both times
- `test_closure_bridge_structure()` — returned bridge has all required keys
- `test_closure_absent_if_empty_last_message()` — `last_message_text = ""` → no closure check
- `test_closure_disabled_via_config()` — `enabled: false` → never fires
