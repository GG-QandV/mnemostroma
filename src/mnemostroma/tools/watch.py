import asyncio
import curses
import json
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path

from mnemostroma.ipc_pool import IPCPool


def _fmt_ts(ts_ms: int) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts_ms / 1000))

def _ago(ts_ms: int) -> str:
    secs = int(time.time() - ts_ms / 1000)
    if secs < 60:   return f"{secs}s ago"
    if secs < 3600: return f"{secs//60}m ago"
    return f"{secs//3600}h ago"

def _connect(db_path: Path) -> sqlite3.Connection | None:
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

def _fetch_health(conn: sqlite3.Connection) -> dict | None:
    try:
        row = conn.execute(
            "SELECT data FROM onnx_logs WHERE component='conductor.health' "
            "ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        return json.loads(row[0]) if row else None
    except Exception:
        return None

class WatchUI:
    def __init__(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0) # Hide cursor
        self.stdscr.nodelay(True) # Non-blocking input
        
        # Initialize colors
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_CYAN, -1)   # Title
        curses.init_pair(2, curses.COLOR_GREEN, -1)  # OK / Active
        curses.init_pair(3, curses.COLOR_YELLOW, -1) # Warning
        curses.init_pair(4, curses.COLOR_RED, -1)    # Error
        curses.init_pair(5, curses.COLOR_BLUE, -1)   # Idle
        curses.init_pair(6, 8, -1)                   # Dim (if supported)

    def draw(self, logs: list, health: dict | None, db_path: Path, interval: int, window_sec: int, is_history: bool = False):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        
        now_str = time.strftime("%H:%M:%S")
        y = 0

        # Title bar
        self.stdscr.addstr(y, 2, "─" * (w - 4), curses.A_DIM)
        y += 1
        self.stdscr.addstr(y, 2, "  MNEMOSTROMA WATCH  ", curses.A_BOLD | curses.color_pair(1))
        self.stdscr.addstr(f"│  {now_str}  ", curses.A_DIM)
        mode_str = f" { '[HISTORIC]' if is_history else '[LIVE]' } "
        self.stdscr.addstr(mode_str, curses.A_REVERSE | curses.color_pair(3 if is_history else 2))
        y += 1
        self.stdscr.addstr(y, 2, f"  db: {db_path.name}  window: {window_sec}s", curses.A_DIM)
        y += 1
        self.stdscr.addstr(y, 2, "─" * (w - 4), curses.A_DIM)
        y += 2

        # Status & Health (Always show if available)
        errors = [l for l in logs if l["level"] == "ERROR"]
        warns = [l for l in logs if l["level"] == "WARNING"]
        
        if not logs and not health:
            self.stdscr.addstr(y, 2, "● ", curses.color_pair(5))
            self.stdscr.addstr("READY / STANDBY", curses.A_BOLD)
            self.stdscr.addstr("  Waiting for daemon activity...")
            y += 2
        else:
            status_pair = 2 if not errors else 4
            status_text = "● ACTIVE " if not is_history else "● READY  "
            
            self.stdscr.addstr(y, 2, status_text, curses.color_pair(status_pair) | curses.A_BOLD)
            if health:
                # Support both IPC (ctx_active) and DB (health) keys
                ram_mb = health.get('ram_mb', 0)
                active_vars = health.get('active_variables', [])
                ram_color = 2 if ram_mb < 500 else 3 if ram_mb < 1000 else 4
                self.stdscr.addstr(" RAM: ", curses.A_DIM)
                self.stdscr.addstr(f"{ram_mb:.0f}MB", curses.color_pair(ram_color) | curses.A_BOLD)
                if active_vars:
                    self.stdscr.addstr(f"  vars: {len(active_vars)}", curses.A_DIM)
            
            self.stdscr.addstr(f"  events: {len(logs)}", curses.A_DIM)
            if errors: self.stdscr.addstr(f"  err: {len(errors)}", curses.color_pair(4))
            if warns: self.stdscr.addstr(f"  warn: {len(warns)}", curses.color_pair(3))
            y += 2

        if logs:
            # Section: Observer
            self.stdscr.addstr(y, 2, "OBSERVER", curses.color_pair(1) | curses.A_BOLD)
            y += 1
            self.stdscr.addstr(y, 2, "─" * 20, curses.A_DIM)
            y += 1
            
            by_comp = defaultdict(list)
            for l in logs: by_comp[l["component"]].append(l)
            
            filter_logs = by_comp.get("observer.filter", [])
            if filter_logs:
                dist = Counter(l["data"].get("importance") for l in filter_logs)
                dist_str = " ".join([f"{k}x{v}" for k, v in dist.items()])
                self.stdscr.addstr(y, 4, f"filter: {dist_str}")
                y += 1
            
            score_logs = by_comp.get("observer.score", [])
            if score_logs:
                avg_s = sum(l["data"].get("score", 0) for l in score_logs) / len(score_logs)
                self.stdscr.addstr(y, 4, f"score:  avg {avg_s:.3f}")
                y += 1

            # Section: Search & Memory
            if y < h - 4:
                y += 1
                self.stdscr.addstr(y, 2, "SEARCH & MEMORY", curses.color_pair(1) | curses.A_BOLD)
                y += 1
                search_logs = by_comp.get("matrix.search", [])
                if search_logs:
                    lats = [l["latency_ms"] for l in search_logs if l["latency_ms"]]
                    avg_lat = sum(lats)/len(lats) if lats else 0
                    self.stdscr.addstr(y, 4, f"search: {len(search_logs)} q  avg {avg_lat:.1f}ms", curses.color_pair(2 if avg_lat < 25 else 3))
                    y += 1
                
                conflict_logs = by_comp.get("tuner.conflict", [])
                if conflict_logs:
                    hits = sum(1 for l in conflict_logs if l["data"].get("conflict_detected"))
                    self.stdscr.addstr(y, 4, f"conflicts: {hits} detected / {len(conflict_logs)} checked", curses.color_pair(4 if hits else 2))
                    y += 1

            # Section: Experience signals
            exp_logs = by_comp.get("experience.signal", [])
            if exp_logs and y < h - 4:
                y += 1
                self.stdscr.addstr(y, 2, "EXPERIENCE LAYER", curses.color_pair(1) | curses.A_BOLD)
                y += 1
                for l in exp_logs[:2]:
                    if y >= h - 2: break
                    tag = l["data"].get("tag", "?")
                    type_str = l["data"].get("type", "?")
                    self.stdscr.addstr(y, 4, f"▸ {tag} [{type_str}]", curses.color_pair(2 if type_str=="DO_THIS" else 3))
                    y += 1

            # Error log (last 2)
            if errors and y < h - 4:
                y += 1
                self.stdscr.addstr(y, 2, "LATEST ERRORS", curses.color_pair(4) | curses.A_BOLD)
                y += 1
                for e in errors[:2]:
                    if y >= h - 1: break
                    err_msg = e["data"].get("error",'')[:w-30]
                    self.stdscr.addstr(y, 4, f"✗ [{_fmt_ts(e['ts'])}] {err_msg}", curses.color_pair(4))
                    y += 1

        self.stdscr.addstr(h-1, 2, "Press 'q' or Ctrl+C to exit", curses.A_DIM)
        self.stdscr.refresh()

async def run_watch_curses(stdscr, db_path: Path, interval: int, window_sec: int):
    ui = WatchUI(stdscr)
    conn = _connect(db_path)
    if not conn:
        return

    sock_path = str(db_path.parent / "daemon.sock")
    pool = IPCPool(sock_path, size=1)
    try:
        await pool.start()
    except Exception:
        pool = None # Degraded mode: SQLite only

    try:
        while True:
            # Check for input
            ch = stdscr.getch()
            if ch == ord('q'): break
            
            # Logic: If no events in last 30s, check if there's anything in last 5m.
            # If still nothing, check if the DB file was modified recently (daemon is alive).
            since_ms_live = int((time.time() - window_sec) * 1000)
            logs = _fetch(conn, since_ms_live)
            is_history = False
            
            if not logs:
                since_ms_recent = int((time.time() - 300) * 1000) # 5 minutes
                logs = _fetch(conn, since_ms_recent)
                if not logs:
                    # Check DB file modification time as a last resort for "liveness"
                    db_mtime_age = time.time() - db_path.stat().st_mtime
                    if db_mtime_age < 300: # 5 minutes
                        # Still fetch top logs for context, but keep is_history=False
                        logs = _fetch(conn, 0)[:50]
                        is_history = False
                    else:
                        # Truly historic
                        logs = _fetch(conn, 0)[:50]
                        is_history = True
                else:
                    is_history = False # Still consider "live" if active in last 5m
            
            # Hybrid Health: IPC first, then fallback to DB log
            health = None
            if pool:
                try:
                    # ctx_active returns {ram_mb, ram_index_count, active_variables, ...}
                    health = await pool.call("ctx_active", {})
                except Exception:
                    health = None
            
            if health is None:
                health = _fetch_health(conn)
            
            ui.draw(logs, health, db_path, interval, window_sec, is_history=is_history)
            await asyncio.sleep(interval)
    finally:
        if pool: await pool.stop()
        conn.close()

def run_watch(db_path: Path, interval: int = 2, window_sec: int = 30):
    """Main watch loop. Falls back to text mode if curses unavailable."""
    try:
        asyncio.run(curses.wrapper(run_watch_curses, db_path, interval, window_sec))
    except (KeyboardInterrupt, SystemExit):
        pass
    except Exception as e:
        # Fallback to simple text mode
        print(f"⚠️  Watch failed: {e.__class__.__name__}. Switching to text mode...")
        _run_watch_text(db_path, interval, window_sec)

def _run_watch_text(db_path: Path, interval: int, window_sec: int):
    """Simple text-based watch output (no curses)."""
    conn = _connect(db_path)
    if not conn:
        print(f"❌ Cannot connect to {db_path}")
        return

    try:
        count = 0
        while True:
            count += 1
            print(f"\n📊 Mnemostroma Watch — Refresh #{count} ({_fmt_ts(int(time.time() * 1000))})")
            print("=" * 80)

            since_ms = int((time.time() - window_sec) * 1000)
            logs = _fetch(conn, since_ms)

            if logs:
                print(f"Last {len(logs)} events ({window_sec}s window):")
                for i, log in enumerate(logs[:10], 1):
                    level_icon = "✓" if log["level"] == "INFO" else "⚠️ " if log["level"] == "WARNING" else "✗"
                    print(f"  {i}. [{_fmt_ts(log['ts'])}] {level_icon} {log['component']} — {log['event']}")
            else:
                print(f"No events in last {window_sec}s (showing history)")
                logs = _fetch(conn, 0)[:10]
                for i, log in enumerate(logs, 1):
                    print(f"  {i}. [{_fmt_ts(log['ts'])}] {log['component']} — {log['event']}")

            health = _fetch_health(conn)
            if health:
                print(f"\n💚 Health: Sessions={health.get('session_count')}, RAM={health.get('ram_mb'):.1f}MB")

            print(f"\nPress Ctrl+C to exit | Next refresh in {interval}s...")
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n✓ Watch stopped")
    finally:
        conn.close()
