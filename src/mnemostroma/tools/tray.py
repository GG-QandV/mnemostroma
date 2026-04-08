# SPDX-License-Identifier: FSL-1.1-MIT
"""mnemostroma tray — system tray status indicator.

Floating coloured circle in the OS taskbar/tray that reflects
the live health of the Mnemostroma daemon.

Colour legend:
  Blue   #4A90D9  — idle / waiting (no activity >30s)
  Teal   #00ACC1  — connected / recent (activity 5–30s ago)
  Green  #66BB6A  — processing (activity in last 5s)
  Yellow #FFC107  — warning (WARNING-level log in last 60s)
  Red    #E53935  — error / daemon not responding

Install extras: pip install mnemostroma[tray]
Usage:          mnemostroma tray [--db logs.db] [--interval 3]
"""
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional

# ── Status constants ────────────────────────────────────────────
_ST_PROCESSING = "processing"
_ST_CONNECTED  = "connected"
_ST_IDLE       = "idle"
_ST_WARNING    = "warning"
_ST_ERROR      = "error"

_COLOURS = {
    _ST_PROCESSING: (102, 187, 106),   # #66BB6A green  — active right now
    _ST_CONNECTED:  (0,   172, 193),   # #00ACC1 teal   — connected, idle
    _ST_IDLE:       (74,  144, 217),   # #4A90D9 blue   — waiting
    _ST_WARNING:    (255, 193, 7),     # #FFC107 yellow — warnings
    _ST_ERROR:      (229, 57,  53),    # #E53935 red    — error
}

_LABELS = {
    _ST_PROCESSING: "Mnemostroma: processing",
    _ST_CONNECTED:  "Mnemostroma: connected",
    _ST_IDLE:       "Mnemostroma: idle",
    _ST_WARNING:    "Mnemostroma: warning",
    _ST_ERROR:      "Mnemostroma: error / not running",
}

_SIZE = 64   # icon canvas size in px
_R    = 28   # circle radius


def _make_icon(status: str):
    """Draw a coloured circle with a subtle shadow using Pillow."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (_SIZE, _SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = _SIZE // 2, _SIZE // 2
    rgb = _COLOURS.get(status, _COLOURS[_ST_IDLE])

    # Shadow
    shadow_offset = 2
    draw.ellipse(
        [cx - _R + shadow_offset, cy - _R + shadow_offset,
         cx + _R + shadow_offset, cy + _R + shadow_offset],
        fill=(0, 0, 0, 60)
    )
    # Main circle
    draw.ellipse(
        [cx - _R, cy - _R, cx + _R, cy + _R],
        fill=(*rgb, 255)
    )
    # Highlight — small white shimmer top-left
    hw = _R // 3
    draw.ellipse(
        [cx - _R + 6, cy - _R + 6,
         cx - _R + 6 + hw, cy - _R + 6 + hw],
        fill=(255, 255, 255, 90)
    )
    return img


# ── DB polling ──────────────────────────────────────────────────

def _detect_status(db_path: Path) -> str:
    """Query logs.db and return current status string."""
    if not db_path.exists():
        return _ST_ERROR

    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        now_ms = int(time.time() * 1000)

        # Last any event
        row = conn.execute(
            "SELECT ts, level FROM onnx_logs ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        if row is None:
            conn.close()
            return _ST_IDLE

        last_ts, last_level = row
        secs_ago = (now_ms - last_ts) / 1000

        # Errors in last 60s
        errors = conn.execute(
            "SELECT COUNT(*) FROM onnx_logs WHERE level='ERROR' AND ts > ?",
            (now_ms - 60_000,)
        ).fetchone()[0]

        # Warnings in last 60s
        warnings = conn.execute(
            "SELECT COUNT(*) FROM onnx_logs WHERE level='WARNING' AND ts > ?",
            (now_ms - 60_000,)
        ).fetchone()[0]

        conn.close()

        if errors:
            return _ST_ERROR
        if warnings:
            return _ST_WARNING
        if secs_ago < 5:
            return _ST_PROCESSING
        if secs_ago < 30:
            return _ST_CONNECTED
        # Check if daemon was ever alive (health check exists)
        return _ST_IDLE

    except Exception:
        return _ST_ERROR


# ── Tray runner ─────────────────────────────────────────────────

def run_tray(db_path: Path, interval: int = 3):
    """Start the system tray icon. Blocks until user quits."""
    try:
        import pystray
        from PIL import Image, ImageDraw  # noqa: F401 — verify pillow available
    except ImportError as e:
        missing = "pystray" if "pystray" in str(e) else "Pillow"
        print(f"{missing} not installed. Run: pip install mnemostroma[tray]")
        return

    current_status = [_ST_IDLE]
    icon_ref = [None]

    def _poll():
        """Background thread: poll DB and update icon."""
        while True:
            status = _detect_status(db_path)
            if status != current_status[0]:
                current_status[0] = status
                if icon_ref[0]:
                    icon_ref[0].icon  = _make_icon(status)
                    icon_ref[0].title = _LABELS[status]
            time.sleep(interval)

    def _on_quit(icon, item):
        icon.stop()

    def _on_status(icon, item):
        """Show current status in a notification (best-effort)."""
        status = current_status[0]
        try:
            icon.notify(_LABELS[status], "Mnemostroma")
        except Exception:
            pass  # notifications not supported on all platforms

    menu = pystray.Menu(
        pystray.MenuItem("Status", _on_status),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", _on_quit),
    )

    initial_status = _detect_status(db_path)
    current_status[0] = initial_status

    icon = pystray.Icon(
        name="mnemostroma",
        icon=_make_icon(initial_status),
        title=_LABELS[initial_status],
        menu=menu,
    )
    icon_ref[0] = icon

    # Start polling thread
    t = threading.Thread(target=_poll, daemon=True)
    t.start()

    icon.run()
