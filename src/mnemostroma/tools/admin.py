# SPDX-License-Identifier: FSL-1.1-MIT
"""Administrative tools for Mnemostroma system monitoring and maintenance."""
import time
import os
import json
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

from ..core import SystemContext
from ..storage.log_writer import log_event
from ..memory.growth_forecast import GrowthForecast

logger = logging.getLogger("mnemostroma.tools.admin")

async def ctx_status(ctx: SystemContext) -> Dict[str, Any]:
    """Retrieve current system status and resource metrics.
    
    Returns:
        Dict containing counts for RAM index, matrix search vectors, and DB info.
    """
    import psutil
    process = psutil.Process()
    ram_mb = process.memory_info().rss / (1024 * 1024)
    
    stats = {
        "timestamp": time.time(),
        "ram_mb_usage": round(ram_mb, 2),
        "ram_index_count": len(ctx.ram_index),
        "urgency_count": len(ctx.urgency_index),
        "session_index": {
            "count": ctx.session_index.get_current_count() if ctx.session_index else 0,
            "max_elements": ctx.session_index.get_max_elements() if ctx.session_index else 0,
        },
        "content_index": {
            "count": ctx.content_index.get_current_count() if ctx.content_index else 0,
        },
        "metrics": ctx.metrics
    }
    
    # Log the status check
    await log_event(ctx, "tools.admin", "status_check", {
        "ram_count": stats["ram_index_count"],
        "index_count": stats["session_index"]["count"]
    })
    
    return stats

async def ctx_sync(ctx: SystemContext) -> bool:
    """Force flush all pending updates to SQLite.

    Ensures that high-priority decisions are committed to disk immediately.
    """
    start = time.time()
    try:
        if ctx.persistence:
            await ctx.persistence.flush()
        
        # Matrix index persistence (no-op by default — numpy grows in RAM)
        pass
            
        latency = (time.time() - start) * 1000
        await log_event(ctx, "tools.admin", "sync", {"latency_ms": latency})
        return True
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return False

async def ctx_dump(ctx: SystemContext, target_dir: Optional[str] = None) -> str:
    """Dump the entire Hot/Warm layer state to a JSON file for debugging.
    
    Args:
        target_dir: Directory to save the dump. Defaults to user home .mnemostroma/dumps.
    """
    if not target_dir:
        target_dir = str(Path.home() / ".mnemostroma" / "dumps")
        
    os.makedirs(target_dir, exist_ok=True)
    filename = f"dump_{int(time.time())}.json"
    filepath = os.path.join(target_dir, filename)
    
    # Extract serializable data
    dump_data = {
        "metadata": {
            "timestamp": time.time(),
            "version": "1.5",
        },
        "ram_index": {
            sid: {
                "brief": sb.brief,
                "importance": sb.importance,
                "created_at": sb.created_at,
                "tags": sb.tags,
                "conflict_flag": sb.conflict_flag
            } for sid, sb in ctx.ram_index.items()
        },
        "urgency": ctx.urgency_index,
        "metrics": ctx.metrics
    }
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(dump_data, f, indent=4, ensure_ascii=False)
        
    await log_event(ctx, "tools.admin", "dump", {"path": filepath})
    return filepath


async def ctx_evict(ctx: SystemContext, n: int = 10) -> int:
    """Internal utility - delegate to Dissolver. NOT an MCP tool.

    Single source of truth: all eviction logic lives in Dissolver.
    Returns number of sessions actually evicted.
    """
    if not getattr(ctx, 'dissolver', None):
        return 0
    before = len(ctx.ram_index)
    await ctx.dissolver.evict_n_oldest(n)
    return before - len(ctx.ram_index)


async def ctx_load(session_id: str, ctx: SystemContext):
    """Load an archived session from SQLite into RAM.

    Public wrapper over lazy_load_session. Use when a session referenced
    in search results is not in RAM (returned None from ctx_get).

    Returns:
        SessionBrief if found, None otherwise.
    """
    if session_id in ctx.ram_index:
        return ctx.ram_index[session_id]

    if ctx.db is None:
        return None

    from ..storage.lazy_loader import lazy_load_session
    sb = await lazy_load_session(session_id, ctx.db)
    if sb is None:
        return None

    ctx.ram_index[session_id] = sb
    label = ctx.get_session_label(session_id)
    ctx.sid_to_id[session_id] = label
    ctx.id_to_sid[label] = session_id

    await log_event(ctx, "tools.admin", "load", {"session_id": session_id})
    return sb


async def ctx_growth(ctx: SystemContext) -> Dict[str, Any]:
    """Analyse session growth rate and project storage capacity.

    Queries SQLite for historical counts and measures file size on disk.
    Latency: <10ms (aggregate queries on small metadata table).
    """
    result: Dict[str, Any] = {
        "sessions_total": 0,
        "sessions_today": 0,
        "sessions_week": 0,
        "sessions_month": 0,
        "db_size_mb": 0.0,
        "logs_size_mb": 0.0,       # ← ДОБАВИТЬ
        "total_size_mb": 0.0,      # ← ДОБАВИТЬ
        "db_growth_per_day_mb": None,
        "days_to_1gb": None,
        "days_to_10gb": None,
    }

    if ctx.db is None:
        return result

    now = int(time.time())
    day_ago   = now - 86400
    week_ago  = now - 7 * 86400
    month_ago = now - 30 * 86400

    try:
        async with ctx.db.execute("SELECT COUNT(*) FROM sessions") as cur:
            row = await cur.fetchone()
            result["sessions_total"] = row[0] if row else 0

        for key, cutoff in [
            ("sessions_today", day_ago),
            ("sessions_week",  week_ago),
            ("sessions_month", month_ago),
        ]:
            async with ctx.db.execute(
                "SELECT COUNT(*) FROM sessions WHERE created_at >= ?", (cutoff,)
            ) as cur:
                row = await cur.fetchone()
                result[key] = row[0] if row else 0

        # DB file path via PRAGMA database_list
        async with ctx.db.execute("PRAGMA database_list") as cur:
            pragma_rows = await cur.fetchall()
        db_path = None
        for pragma_row in pragma_rows:
            if pragma_row[1] == "main" and pragma_row[2]:
                db_path = pragma_row[2]
                break

        if db_path and os.path.exists(db_path):
            size_bytes = os.path.getsize(db_path)
            result["db_size_mb"] = round(size_bytes / (1024 * 1024), 2)

            # --- TASK 1: добавляем logs.db ---
            logs_path = Path.home() / ".mnemostroma" / "logs.db"
            logs_size_mb = round(os.path.getsize(logs_path) / (1024 * 1024), 2) if logs_path.exists() else 0.0
            result["logs_size_mb"] = logs_size_mb
            result["total_size_mb"] = round(result["db_size_mb"] + logs_size_mb, 2)
            # ---------------------------------

            # Growth rate: sessions_today * avg_session_size
            if result["sessions_total"] > 0 and result["db_size_mb"] > 0:
                avg_mb_per_session = result["db_size_mb"] / result["sessions_total"]
                daily_growth_mb = result["sessions_today"] * avg_mb_per_session
                result["db_growth_per_day_mb"] = round(daily_growth_mb, 4)
                if daily_growth_mb > 0:
                    result["days_to_1gb"]  = int((1024  - result["total_size_mb"]) / daily_growth_mb)
                    result["days_to_10gb"] = int((10240 - result["total_size_mb"]) / daily_growth_mb)

                # --- TASK 4: baseline validation ---
                if result["sessions_today"] > 0:
                    actual_kb = (daily_growth_mb * 1024) / result["sessions_today"]
                    deviation_pct = (actual_kb - 3.0) / 3.0 * 100
                    result["per_session_kb"] = round(actual_kb, 2)
                    if abs(deviation_pct) > 50:
                        result["baseline_status"] = "ANOMALY"
                    elif abs(deviation_pct) > 20:
                        result["baseline_status"] = "ELEVATED"
                    else:
                        result["baseline_status"] = "NORMAL"
                # ------------------------------------

        # --- GrowthForecast: two-model projection ---
        _logs_db = Path.home() / ".mnemostroma" / "logs.db"
        _history = await GrowthForecast.load_history(_logs_db, days_back=30)
        _forecast = GrowthForecast(_history)
        _best     = _forecast.best()
        _linear   = _forecast.linear()
        _exp      = _forecast.exponential()
        # --- end GrowthForecast ---

        result["forecast"] = {
            "best_model":       _best.model,
            "daily_rate_mb":    _best.daily_rate_mb,
            "days_to_1gb":      _best.days_to_1gb,
            "days_to_10gb":     _best.days_to_10gb,
            "r_squared":        _best.r_squared,
        }
        result["forecast_linear"] = {
            "daily_rate_mb": _linear.daily_rate_mb,
            "days_to_1gb":   _linear.days_to_1gb,
            "r_squared":     _linear.r_squared,
        }
        result["forecast_exp"] = {
            "daily_rate_mb": _exp.daily_rate_mb,
            "days_to_1gb":   _exp.days_to_1gb,
            "r_squared":     _exp.r_squared,
        }
        result["history_points"] = len(_history)

    except Exception as e:
        logger.error(f"ctx_growth: error: {e}")

    await log_event(ctx, "tools.admin", "growth", {
        "total": result["sessions_total"],
        "db_mb": result["db_size_mb"],
    })
    return result


async def ctx_pulse(ctx: SystemContext) -> Dict[str, Any]:
    """Minimal system heartbeat — pure RAM, <0.01ms.

    Returns session count, process RSS, and RAM usage percentage
    relative to the configured RAM budget (if available).
    """
    sessions = len(ctx.ram_index)
    ram_mb = 0.0
    try:
        import psutil
        ram_mb = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
    except Exception:
        pass

    # RAM budget from config (optional)
    try:
        budget_mb = float(ctx.config.resources.ram_budget_mb)
    except Exception:
        budget_mb = 631.0
    ram_pct = round(ram_mb / budget_mb * 100, 1) if budget_mb > 0 else 0.0

    return {
        "sessions": sessions,
        "ram_mb": ram_mb,
        "ram_pct": ram_pct,
        "urgency_active": len([
            v for v in ctx.urgency_index.values() if not v.get("expired", False)
        ]) if hasattr(ctx, "urgency_index") else 0,
    }


async def ctx_bridge(ctx: SystemContext) -> Dict[str, Any]:
    """Generate a structured handoff packet for the next agent.

    Unlike ctx_inject (which builds XML for the current agent's prompt),
    ctx_bridge returns a structured dict with everything the next agent
    needs to continue work without losing context.

    Returns:
        Dict with: intent_summary, active_variables, last_decisions,
                   open_issues, urgency_active, ram_sessions.
    """
    sessions = sorted(ctx.ram_index.values(), key=lambda x: x.created_at, reverse=True)

    intent_summary = sessions[0].brief if sessions else "No active sessions."

    active_variables: List[str] = [
        f"[{sb.importance}] {sb.brief}"
        for sb in sessions
        if sb.importance in ("critical", "principle")
    ][:9]

    last_decisions: List[str] = [
        sb.brief for sb in sessions
        if sb.importance in ("critical", "important")
    ][:5]

    open_issues: List[str] = [
        sb.brief for sb in sessions if sb.conflict_flag
    ][:5]

    urgency_active = sorted(
        [v for v in ctx.urgency_index.values() if not v.get("expired", False)],
        key=lambda x: x.get("deadline_ts") or 9999999999,
    ) if hasattr(ctx, "urgency_index") else []

    result = {
        "intent_summary": intent_summary,
        "active_variables": active_variables,
        "last_decisions": last_decisions,
        "open_issues": open_issues,
        "urgency_active": urgency_active[:3],
        "ram_sessions": len(ctx.ram_index),
    }

    await log_event(ctx, "tools.admin", "bridge", {
        "variables": len(active_variables),
        "decisions": len(last_decisions),
        "open_issues": len(open_issues),
    })
    return result
