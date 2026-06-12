import logging
import re
import time
from typing import Any

from ..core import SystemContext
from ..feedback.implicit import signal_use
from ..memory.search import semantic_search
from .admin import ctx_bridge as _ctx_bridge
from .response_builder import build_search_response
from .time_utils import enrich_with_time, parse_exact_time_with_mask

logger = logging.getLogger("mnemostroma.tools.read")

# --- Urgency Pulse (Phase 11.F) ---
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3, "overdue": 4}

def _compute_urgency_level(deadline_ts: float) -> str:
    """Compute urgency level based on hours left until deadline."""
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

def _urgency_pulse(ctx: SystemContext) -> list[dict[str, Any]]:
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

# --- Session Closure (Phase 11.G) ---
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

async def ctx_get(session_id: str, ctx: SystemContext) -> Any | None:
    """Retrieve session from RAM or lazy load via session_repo."""
    if session_id in ctx.ram_index:
        sb = ctx.ram_index[session_id]
        await signal_use(session_id, ctx)
        return sb

    # Lazy load via Repository
    if ctx.session_repo:
        sb, error = await ctx.session_repo.load(session_id)
        if error is None:
            ctx.ram_index[session_id] = sb
            label = ctx.get_session_label(session_id)
            ctx.sid_to_id[session_id] = label
            ctx.id_to_sid[label] = session_id
            await signal_use(session_id, ctx)
            return sb

    return None

async def ctx_semantic(
    query: str, 
    ctx: SystemContext, 
    k: int = 20, 
    top_n: int = 5
) -> list[Any]:
    """Perform high-precision semantic search.

    Feeds returned session IDs into ImplicitFeedbackTracker for IGNORE
    detection (rapid re-query < 5s) and deferred USE signals.

    Args:
        query: Search query string.
        ctx: System context.
        k: Candidates limit for ANN.
        top_n: Final results after reranking.
    """
    start = time.time()
    results = await semantic_search(query, ctx, k=k, top_n=top_n)
    latency = (time.time() - start) * 1000

    # B02: Emit IGNORE/USE signals via tracker (feedback_loop_v1.5.md § 4)
    tracker = getattr(ctx, "feedback_tracker", None)
    if tracker:
        returned_ids = [sb.session_id for sb in results]
        await tracker.on_semantic_query(returned_ids)

    # Log tool call (v1.0 spec Point #13)

    return results

async def ctx_search(
    tags: list[str],
    ctx: SystemContext,
    importance: str | None = None,
    age: str | None = None,
    limit: int = 10,
    exact_time: str | None = None,
) -> dict[str, Any] | list[Any]:
    """Search sessions by tags (RAM) or by exact time with optional tag filter.

    When exact_time is provided:
        - Parses the time string with optional X-mask (minute/hour/day precision)
        - Scans RAM index for matching sessions; falls back to SQL if RAM is empty
        - Applies tags/importance as additional filters (tags=[] skips tag filter)
        - Returns a SearchResponse dict with tiered protection against context overflow

    When exact_time is absent:
        - Legacy behaviour: pure RAM tag-intersection scan
        - tags must be non-empty

    Args:
        tags: Tag intersection filter. Optional when exact_time is provided.
        ctx: SystemContext.
        importance: Optional importance filter.
        age: Optional age_signal filter (legacy path only).
        limit: Max results for legacy path; not applied to exact_time path.
        exact_time: Time string with optional X-mask, e.g. "27/04/26 21:18:XX".

    Returns:
        dict (SearchResponse) when exact_time is provided.
        List[SessionBrief] for legacy tag-only path (backward compatible).
    """
    # ── PLAN B: exact_time path ──────────────────────────────────────────────
    if exact_time is not None:
        # 1. Parse time string → [lo, hi)
        lo, hi = parse_exact_time_with_mask(exact_time)
        if lo is None:
            # hi holds the error message when lo is None
            error_msg: str = hi  # type: ignore[assignment]
            return [{"error": error_msg, "exact_time_received": exact_time}]

        # 2. RAM scan — fast path (~0.1ms)
        candidates: list[dict[str, Any]] = [
            {
                "session_id": sb.session_id,
                "brief": sb.brief,
                "created_at": sb.created_at,
                "importance": sb.importance,
                "tags": list(getattr(sb, "tags", [])),
            }
            for sb in ctx.ram_index.values()
            if lo <= sb.created_at < hi
        ]

        # 3. SQL fallback when RAM returns nothing (evicted sessions)
        if not candidates and ctx.session_repo is not None:
            # Use a high internal limit so build_search_response sees the full count
            _SQL_SCAN_LIMIT = 200
            result = await ctx.session_repo.search_by_time_window(lo, hi, _SQL_SCAN_LIMIT)
            if result.is_ok():
                candidates = result.unwrap() or []
            else:
                logger.warning("ctx_search SQL fallback failed: %s", result)

        # 4. Apply additional filters on top
        tag_set = set(tags) if tags else set()
        filtered: list[dict[str, Any]] = [
            r for r in candidates
            if (not tag_set or tag_set.issubset(set(r.get("tags", []))))
            and (importance is None or r.get("importance") == importance)
        ]

        # 5. Enrich each result with human-readable time
        for r in filtered:
            enrich_with_time(r)

        # 6. Build tiered response (full / warning / compact)
        response = build_search_response(filtered, total_matched=len(filtered))

        return response

    # ── PLAN A legacy: tag-only RAM scan ─────────────────────────────────────
    if not tags:
        raise ValueError(
            "ctx_search requires at least one tag when exact_time is not provided. "
            "Provide tags=[] together with exact_time for time-only search."
        )

    tag_set = set(tags)
    results = [
        sb for sb in ctx.ram_index.values()
        if tag_set.issubset(set(sb.tags))
        and (importance is None or sb.importance == importance)
        and (age is None or getattr(sb, 'age_signal', None) == age)
    ]
    results.sort(key=lambda x: x.score, reverse=True)
    return results[:limit]


async def ctx_full(
    session_id: str,
    ctx: SystemContext,
    max_chars: int = 2000
) -> dict[str, Any] | None:
    """Load full session record via session_repo including content_full.

    Truncates content_full to max_chars to prevent token bloat in agent contexts.
    """
    if not ctx.session_repo:
        return None

    data, error = await ctx.session_repo.load_full(session_id)
    if error is not None:
        return None

    # Apply truncation guard to content_full
    if data and data.get("content_full"):
        content = data["content_full"]
        if len(content) > max_chars:
            data["content_full"] = content[:max_chars] + "\n...[truncated]"

    await signal_use(session_id, ctx)
    return data


async def ctx_anchors(
    ctx: SystemContext,
    anchor_type: str | None = None,
    session_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Read anchors from RAM index (subconscious layer).

    Returns full anchor objects without embedding blobs.
    """
    anchor_index = getattr(ctx, "anchor_index", None)
    if anchor_index is None:
        return []

    if anchor_type:
        anchors = anchor_index.query_by_type(anchor_type)
    else:
        anchors = anchor_index.all()

    if session_id:
        anchors = [a for a in anchors if a.session_id == session_id]

    anchors.sort(key=lambda a: a.last_accessed_at, reverse=True)

    result = []
    for a in anchors[:limit]:
        result.append({
            "anchor_id": a.anchor_id,
            "session_id": a.session_id,
            "anchor_type": a.anchor_type,
            "brief": a.brief,
            "key_facts": a.key_facts,
            "flags": a.flags,
            "decay_level": a.decay_level,
            "access_count": a.access_count,
            "last_accessed_at": a.last_accessed_at,
            "t_rel": a.t_rel,
            "created_at": a.created_at,
        })

    return result


async def ctx_precision(
    ctx: SystemContext,
    precision_type: str | None = None,
    importance: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Read precision artifacts from Repository."""
    if not ctx.precision_repo:
        return []

    result, error = await ctx.precision_repo.list_entries(
        precision_type=precision_type,
        importance=importance,
        limit=limit
    )
    if error is not None:
        return []

    return result


async def ctx_recent(
    ctx: SystemContext,
    days: float = 7.0,
    by: str = "created",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Return sessions observed or accessed within the last N days."""
    import time as _time

    if ctx.session_repo:
        results, error = await ctx.session_repo.load_recent(days, by, limit)
        if error is None:
            return results

    # LEGACY mode fallback: scan ram_index directly
    cutoff = _time.time() - days * 86400
    candidates = [
        sb for sb in ctx.ram_index.values()
        if sb.created_at >= cutoff
    ]
    # by='accessed' → approximate via score (no last_use_ts in RAM)
    candidates.sort(key=lambda x: x.created_at, reverse=True)
    results = candidates[:limit]

    return results



async def ctx_active(ctx: SystemContext) -> dict[str, Any]:
    """Return the current active context summary (bridge) for the agent.
    
    Includes active_variables and urgency_active (v1.3).
    """
    # 1. Intent Summary (Dynamic)
    # Pull from most recent session in RAM or default
    sessions = sorted(ctx.ram_index.values(), key=lambda x: x.created_at, reverse=True)
    intent_summary = sessions[0].brief if sessions else "No active sessions."
    
    # 2. Urgency Active
    urgency_active = sorted(
        [item for item in ctx.urgency_index.values() if not item.get("expired", False)],
        key=lambda x: x.get("deadline_ts", 0) or 9999999999
    )
    
    # 3. Active Variables (Critical/Principle)
    active_vars = [
        f"{k}: {v.brief}" for k, v in ctx.ram_index.items() 
        if v.importance in ("critical", "principle")
    ][:9]
    
    res = {
        "intent_summary": intent_summary,
        "active_variables": active_vars,
        "urgency_active": urgency_active
    }
    
    # 11.D: Precision Guard — value-level discrepancies detected at Step 0.5
    if getattr(ctx.config, "precision_guard", None) and ctx.config.precision_guard.enabled:
        prec_warns = getattr(ctx, "precision_warnings", [])
        if prec_warns:
            res["precision_warnings"] = list(prec_warns)
            prec_warns.clear()

    # 11.C: Anchor Guardian — Layer 1 keyword check (same-turn) + Layer 2 async results
    if ctx.config.anchor_guardian.enabled:
        from ..subconscious.guardian import _keyword_anchor_check, _merge_warnings
        last_text = getattr(ctx, "last_message_text", "")
        kw_warnings = _keyword_anchor_check(last_text, ctx) if last_text else []
        conflict_q = getattr(ctx, "conflict_warnings", [])
        async_warnings = list(conflict_q)
        if hasattr(ctx, "conflict_warnings"):
            ctx.conflict_warnings.clear()
        all_warnings = _merge_warnings(kw_warnings, async_warnings)
        if all_warnings:
            res["conflict_warnings"] = all_warnings

    # 11.A: Associative Surfacing — Layer 1 keyword (same-turn) + Layer 2 async queue
    if ctx.config.associative_surfacing.enabled:
        from ..subconscious.surfacing import _keyword_surface
        last_text = getattr(ctx, "last_message_text", "")
        kw_surfaced = _keyword_surface(last_text, ctx) if last_text else []
        surfaced_q = getattr(ctx, "surfaced_queue", [])
        async_surfaced = list(surfaced_q)
        if hasattr(ctx, "surfaced_queue"):
            ctx.surfaced_queue.clear()
        # Merge: async_surfaced wins on id dedup (has similarity score)
        merged_ids: set = set()
        merged_surfaced = []
        for item in async_surfaced:
            merged_ids.add(item["id"])
            merged_surfaced.append(item)
        for item in kw_surfaced:
            if item["id"] not in merged_ids:
                merged_surfaced.append(item)
        if merged_surfaced:
            res["surfaced"] = merged_surfaced

    # 11.E: Open Loop Detector — pending-outcome anchors (Layer 1 keyword + Layer 2 async)
    if getattr(ctx.config, "open_loop", None) and ctx.config.open_loop.enabled:
        from ..subconscious.guardian import _keyword_open_loop
        last_text = getattr(ctx, "last_message_text", "")
        kw_loops = _keyword_open_loop(last_text, ctx, cooldown_sec=ctx.config.open_loop.cooldown_sec) if last_text else []
        loops_q = getattr(ctx, "open_loops_queue", [])
        async_loops = list(loops_q)
        if hasattr(ctx, "open_loops_queue"):
            ctx.open_loops_queue.clear()
        # Merge: async_loops (with similarity) win on dedup by anchor_id
        merged_loop_ids: set = set()
        merged_loops = []
        for item in async_loops:
            merged_loop_ids.add(item["anchor_id"])
            merged_loops.append(item)
        for item in kw_loops:
            if item["anchor_id"] not in merged_loop_ids:
                merged_loops.append(item)
        if merged_loops:
            res["open_loops"] = merged_loops[:ctx.config.open_loop.max_results]

    # 11.F: Urgency Pulse — escalation events only
    if ctx.config.urgency_pulse.enabled:
        pulse = _urgency_pulse(ctx)
        if pulse:
            res["urgency_pulse"] = pulse

    # 11.G: Session Closure Trigger — farewell check on user's last message
    if ctx.config.session_closure.enabled and ctx.last_message_text:
        now = time.time()
        if (
            _is_farewell(ctx.last_message_text)
            and now > ctx.closure_cooldown_until
        ):
            bridge = await _ctx_bridge(ctx)
            res["session_closure"] = {
                "trigger": "farewell_detected",
                "bridge": bridge,
            }
            ctx.closure_cooldown_until = now + ctx.config.session_closure.cooldown_sec

    # Clear last_message_text after all Layer 1 checks consumed it
    # Prevents stale text from re-firing same-turn keyword signals next call
    ctx.last_message_text = ""

    # Log tool call (v1.0 spec)

    return res
