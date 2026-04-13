# SPDX-License-Identifier: FSL-1.1-MIT
"""mnemostroma watch — live terminal observer.

Polls logs.db every N seconds and renders a live status dashboard.
No daemon connection required — reads directly from the log database.
"""
import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

# ANSI colours
_R  = "\033[0m"       # reset
_B  = "\033[1m"       # bold
_DIM = "\033[2m"
_RED    = "\033[31m"
_GRN    = "\033[32m"
_YEL    = "\033[33m"
_BLU    = "\033[34m"
_CYN    = "\033[36m"
_GRN2   = "\033[92m"  # bright green


def _clear():
    os.system("cls" if os.name == "nt" else "clear")


def _fmt_ts(ts_ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts_ms / 1000))


def _ago(ts_ms: int) -> str:
    secs = int(time.time() - ts_ms / 1000)
    if secs < 60:   return f"{secs}s ago"
    if secs < 3600: return f"{secs//60}m ago"
    return f"{secs//3600}h ago"


def _status_dot(last_event_ts_ms: Optional[int], has_error: bool, has_warning: bool) -> str:
    if has_error:
        return f"{_RED}● ERROR{_R}"
    if last_event_ts_ms is None:
        return f"{_BLU}● IDLE{_R}"
    secs = time.time() - last_event_ts_ms / 1000
    if secs < 5:
        return f"{_GRN2}● ACTIVE{_R}"
    if secs < 30:
        return f"{_GRN}● RECENT{_R}"
    if has_warning:
        return f"{_YEL}● WARNING{_R}"
    return f"{_BLU}● IDLE{_R}"


def _connect(db_path: Path) -> Optional[sqlite3.Connection]:
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn
    except Exception:
        return None


def _fetch(conn: sqlite3.Connection, since_ms: int) -> list:
    try:
        rows = conn.execute(
            "SELECT ts, component, event, data, latency_ms, session_id, level "
            "FROM onnx_logs WHERE ts > ? ORDER BY ts DESC LIMIT 500",
            (since_ms,)
        ).fetchall()
        result = []
        for r in rows:
            try:
                data = json.loads(r["data"])
            except Exception:
                data = {}
            result.append({
                "ts": r["ts"], "component": r["component"], "event": r["event"],
                "data": data, "latency_ms": r["latency_ms"] or 0.0,
                "session_id": r["session_id"], "level": r["level"],
            })
        return result
    except Exception:
        return []


def _fetch_health(conn: sqlite3.Connection) -> Optional[dict]:
    """Get latest health check entry."""
    try:
        row = conn.execute(
            "SELECT data FROM onnx_logs WHERE component='conductor.health' "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None


def _render(logs: list, health: Optional[dict], db_path: Path, interval: int, window_sec: int):
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")

    # ── Aggregate ──────────────────────────────────────────────
    by_component = defaultdict(list)
    for l in logs:
        by_component[l["component"]].append(l)

    errors   = [l for l in logs if l["level"] == "ERROR"]
    warnings = [l for l in logs if l["level"] == "WARNING"]
    last_ts  = logs[0]["ts"] if logs else None

    # Observer filter stats
    filter_logs = by_component.get("observer.filter", [])
    importance_dist = Counter(l["data"].get("importance") for l in filter_logs)

    # Score stats
    score_logs = by_component.get("observer.score", [])
    scores = [l["data"].get("score", 0) for l in score_logs if "score" in l["data"]]

    # Matrix search latency
    search_logs = by_component.get("matrix.search", [])
    search_latencies = [l["latency_ms"] for l in search_logs if l["latency_ms"]]

    # Conflicts
    conflict_logs = by_component.get("tuner.conflict", [])
    conflicts_hit = sum(1 for l in conflict_logs if l["data"].get("conflict_detected"))

    # Feedback
    fb_logs = by_component.get("feedback.implicit", [])
    fb_counts = Counter(l["data"].get("type") for l in fb_logs)

    # Experience signals
    exp_logs = by_component.get("experience.signal", [])
    exp_by_type = Counter(l["data"].get("type") for l in exp_logs)
    exp_tags = {}
    for l in exp_logs:
        tag = l["data"].get("tag", "?")
        exp_tags[tag] = {
            "type": l["data"].get("type"),
            "maturity": l["data"].get("maturity", "?"),
            "avg_score": l["data"].get("avg_score", 0),
            "ts": l["ts"],
        }

    # Calibration
    cal_logs = by_component.get("calibration.update", [])
    cal_last = cal_logs[0] if cal_logs else None

    # Storage flush
    flush_logs = by_component.get("storage.flush", [])
    total_flushed = sum(l["data"].get("flushed_count", 0) for l in flush_logs)

    # ── Render ──────────────────────────────────────────────────
    lines = []
    W = 62

    def hr(char="─"):
        lines.append(_DIM + char * W + _R)

    def section(title):
        lines.append(f"\n{_B}{_CYN}{title}{_R}")
        hr()

    # Header
    lines.append(f"{_B}{'─'*W}{_R}")
    lines.append(f"{_B}  MNEMOSTROMA WATCH  {_DIM}│{_R}  {now_str}  {_DIM}[{interval}s]{_R}")
    lines.append(f"  db: {_DIM}{db_path}{_R}  window: {window_sec}s")
    lines.append(f"{_B}{'─'*W}{_R}")

    # Status line
    status = _status_dot(last_ts, bool(errors), bool(warnings))
    ram = f"  RAM: {_B}{health['ram_mb']:.0f}MB{_R}" if health and health.get("ram_mb", -1) >= 0 else ""
    lines.append(f"\n  {status}{ram}  events: {_B}{len(logs)}{_R}  errors: {_RED if errors else _DIM}{len(errors)}{_R}  warns: {_YEL if warnings else _DIM}{len(warnings)}{_R}\n")

    # Observer
    section("OBSERVER")
    if filter_logs:
        dist_str = "  ".join(
            f"{_GRN if k=='critical' else _YEL if k=='important' else _DIM}{k}×{v}{_R}"
            for k, v in importance_dist.most_common()
        )
        lines.append(f"  filter    {dist_str or '—'}")
    else:
        lines.append(f"  filter    {_DIM}no events{_R}")

    if scores:
        avg_s = sum(scores)/len(scores)
        color = _GRN if avg_s > 0.6 else _YEL if avg_s > 0.4 else _RED
        lines.append(f"  score     avg {color}{avg_s:.3f}{_R}  min {min(scores):.3f}  max {max(scores):.3f}  ({len(scores)} sessions)")
    else:
        lines.append(f"  score     {_DIM}no events{_R}")

    # Search
    section("SEARCH & MEMORY")
    if search_logs:
        avg_lat = sum(search_latencies)/len(search_latencies) if search_latencies else 0
        lat_color = _GRN if avg_lat < 25 else _YEL if avg_lat < 50 else _RED
        lines.append(f"  search{len(search_logs)} queries  avg {lat_color}{avg_lat:.1f}ms{_R}")
    else:
        lines.append(f"  search{_DIM}no queries{_R}")

    if conflict_logs:
        c_color = _RED if conflicts_hit else _GRN
        lines.append(f"  conflicts {c_color}{conflicts_hit} detected{_R} / {len(conflict_logs)} checked")
    else:
        lines.append(f"  conflicts {_DIM}no checks{_R}")

    if flush_logs:
        lines.append(f"  storage   {total_flushed} sessions flushed  ({len(flush_logs)} batches)")

    # Feedback
    if fb_logs:
        section("FEEDBACK")
        fb_str = "  ".join(f"{_GRN}{k}×{v}{_R}" for k, v in fb_counts.most_common())
        lines.append(f"  signals   {fb_str}")

    # Experience
    section("EXPERIENCE LAYER")
    if exp_logs:
        type_str = "  ".join(
            f"{''+_GRN2 if t=='DO_THIS' else _YEL if t=='TENSION' else _RED}{t}×{n}{_R}"
            for t, n in exp_by_type.most_common()
        )
        lines.append(f"  fired     {type_str}")
        for tag, info in list(exp_tags.items())[:5]:
            t_color = _GRN2 if info["type"]=="DO_THIS" else _YEL if info["type"]=="TENSION" else _RED
            lines.append(f"  {t_color}▸{_R} {_B}{tag}{_R} [{info['maturity']}]  score {info['avg_score']:.2f}  {_DIM}{_ago(info['ts'])}{_R}")
    else:
        lines.append(f"  {_DIM}no signals in this window{_R}")

    # Calibration
    if cal_last:
        section("CALIBRATION")
        d = cal_last["data"]
        arrow = f"{d.get('threshold_old','?')} → {_GRN}{d.get('threshold_new','?')}{_R}"
        lines.append(f"  threshold {arrow}  ({d.get('samples','?')} samples)")

    # Errors / Warnings
    if errors:
        section(f"{_RED}ERRORS{_R}")
        for e in errors[:3]:
            lines.append(f"  {_RED}✗{_R} [{_fmt_ts(e['ts'])}] {e['component']}  {e['data'].get('error','')[:50]}")

    if warnings:
        section(f"{_YEL}WARNINGS{_R}")
        for w in warnings[:3]:
            lines.append(f"  {_YEL}⚠{_R} [{_fmt_ts(w['ts'])}] {w['component']}")

    if not errors and not warnings and logs:
        lines.append(f"\n  {_GRN}✓ No issues{_R}")

    lines.append(f"\n{_DIM}{'─'*W}{_R}")
    lines.append(f"{_DIM}  Ctrl+C to exit{_R}\n")

    _clear()
    print("\n".join(lines))


def run_watch(db_path: Path, interval: int = 2, window_sec: int = 30):
    """Main watch loop."""
    print(f"Connecting to {db_path}...")

    conn = _connect(db_path)
    if conn is None:
        print(f"logs.db not found at {db_path}")
        print("Start the daemon first: mnemostroma run")
        return

    print("Connected. Starting live view (Ctrl+C to stop)...")
    time.sleep(0.5)

    try:
        while True:
            since_ms = int((time.time() - window_sec) * 1000)
            logs = _fetch(conn, since_ms)
            health = _fetch_health(conn)
            _render(logs, health, db_path, interval, window_sec)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nWatch stopped.")
    finally:
        conn.close()
