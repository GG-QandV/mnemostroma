# SPDX-License-Identifier: FSL-1.1-MIT
"""mnemostroma tray — AppIndicator system tray (Linux native).

Memory layer indicator for Mnemostroma with animated color transitions.

Colour legend with smooth transitions:
  Blue   #4A90D9  — idle / waiting (no activity >30s)
  Teal   #00ACC1  — connected / recent (activity 5–30s ago)
  Green  #66BB6A  — processing (activity in last 5s)
  Yellow #FFC107  — warning (WARNING-level log in last 60s)
  Red    #E53935  — error / daemon not responding
"""
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

try:
    import gi
    gi.require_version('Gtk', '3.0')
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import Gtk, GLib
    from gi.repository import AppIndicator3 as appindicator
    HAS_APPINDICATOR = True
except (ImportError, ValueError):
    HAS_APPINDICATOR = False

# ── Status constants ────────────────────────────────────────────
_ST_PROCESSING = "processing"
_ST_CONNECTED = "connected"
_ST_IDLE = "idle"
_ST_WARNING = "warning"
_ST_ERROR = "error"

_COLOURS = {
    _ST_PROCESSING: "#66BB6A",  # green
    _ST_CONNECTED: "#00ACC1",   # teal
    _ST_IDLE: "#4A90D9",        # blue
    _ST_WARNING: "#FFC107",     # yellow
    _ST_ERROR: "#E53935",       # red
}

_LABELS = {
    _ST_PROCESSING: "Mnemostroma: processing",
    _ST_CONNECTED: "Mnemostroma: connected",
    _ST_IDLE: "Mnemostroma: idle",
    _ST_WARNING: "Mnemostroma: warning",
    _ST_ERROR: "Mnemostroma: error / not running",
}

_SIZE = 64
_ANIM_DURATION = 3.0  # seconds for color transition
_ANIM_STEPS = 60  # frames for smooth animation


def _hex_to_rgb(hex_color: str) -> tuple:
    """Convert hex color to RGB tuple (0-1 range)."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) / 255.0 for i in (0, 2, 4))


def _rgb_to_hex(r: float, g: float, b: float) -> str:
    """Convert RGB (0-1) to hex color."""
    return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"


def _interpolate_color(color1: str, color2: str, t: float) -> str:
    """Interpolate between two colors. t=0 -> color1, t=1 -> color2."""
    r1, g1, b1 = _hex_to_rgb(color1)
    r2, g2, b2 = _hex_to_rgb(color2)

    r = r1 + (r2 - r1) * t
    g = g1 + (g2 - g1) * t
    b = b1 + (b2 - b1) * t

    return _rgb_to_hex(r, g, b)


def _make_memory_icon(color: str) -> str:
    """Create SVG icon: stacked memory layers (3 blocks stacked)."""
    r, g, b = _hex_to_rgb(color)
    rgb_str = f"{int(r*255)},{int(g*255)},{int(b*255)}"

    # Three stacked blocks (memory layers)
    svg = f"""<?xml version="1.0" encoding="UTF-8"?>
<svg width="{_SIZE}" height="{_SIZE}" xmlns="http://www.w3.org/2000/svg">
  <!-- Background -->
  <rect width="{_SIZE}" height="{_SIZE}" fill="transparent"/>

  <!-- Memory layer 3 (bottom) -->
  <rect x="12" y="44" width="40" height="12" fill="rgb({rgb_str})" opacity="0.5" rx="2"/>

  <!-- Memory layer 2 (middle) -->
  <rect x="10" y="28" width="44" height="14" fill="rgb({rgb_str})" opacity="0.75" rx="2"/>

  <!-- Memory layer 1 (top) -->
  <rect x="8" y="10" width="48" height="16" fill="rgb({rgb_str})" rx="2"/>

  <!-- Highlight on top layer -->
  <rect x="10" y="12" width="8" height="4" fill="white" opacity="0.4" rx="1"/>
</svg>"""
    return svg


def _detect_status(db_path: Path) -> str:
    """Query logs.db and return current status string."""
    if not db_path.exists():
        return _ST_ERROR

    try:
        conn = sqlite3.connect(str(db_path), timeout=2)
        now_ms = int(time.time() * 1000)

        row = conn.execute(
            "SELECT ts, level FROM onnx_logs ORDER BY ts DESC LIMIT 1"
        ).fetchone()

        if row is None:
            conn.close()
            return _ST_IDLE

        last_ts, last_level = row
        secs_ago = (now_ms - last_ts) / 1000

        errors = conn.execute(
            "SELECT COUNT(*) FROM onnx_logs WHERE level='ERROR' AND ts > ?",
            (now_ms - 60_000,)
        ).fetchone()[0]

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
        return _ST_IDLE

    except Exception:
        return _ST_ERROR


class DaemonTrayApp:
    """AppIndicator system tray for Mnemostroma (Linux) with animated colors."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.indicator = None
        self.current_status = _ST_IDLE
        self.target_status = _ST_IDLE
        self.running = True
        self.animation_start = time.time()
        self.animation_active = False
        self._init_indicator()

    def _open_watch(self, widget=None):
        """Open 'mnemostroma watch' in terminal."""
        try:
            terminals = [
                ["x-terminal-emulator", "-e", "bash", "-c", "mnemostroma watch; bash"],
                ["gnome-terminal", "--", "bash", "-c", "mnemostroma watch; bash"],
                ["konsole", "-e", "bash", "-c", "mnemostroma watch; bash"],
                ["xterm", "-e", "bash", "-c", "mnemostroma watch; bash"],
            ]
            for term_cmd in terminals:
                try:
                    subprocess.Popen(term_cmd)
                    return
                except FileNotFoundError:
                    continue
        except Exception as e:
            print(f"Error opening watch: {e}")

    def _restart_daemon(self, widget=None):
        """Restart mnemostroma daemon."""
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "mnemostroma-daemon"],
                timeout=10
            )
            print("Daemon restarted")
        except Exception as e:
            print(f"Error restarting daemon: {e}")

    def _show_status(self, widget=None):
        """Show status."""
        status = self.current_status
        print(f"Status: {_LABELS[status]}")

    def _animate_to_status(self, target_status: str):
        """Start smooth color animation to target status."""
        if target_status == self.current_status and not self.animation_active:
            return

        self.target_status = target_status
        self.animation_start = time.time()
        self.animation_active = True

    def _update_animation(self):
        """Update animation frame."""
        if not self.animation_active or not self.indicator:
            return

        elapsed = time.time() - self.animation_start
        progress = min(elapsed / _ANIM_DURATION, 1.0)

        # Interpolate color between current and target
        current_color = _COLOURS[self.current_status]
        target_color = _COLOURS[self.target_status]
        animated_color = _interpolate_color(current_color, target_color, progress)

        # Update icon with animated color
        svg = _make_memory_icon(animated_color)
        # AppIndicator doesn't support direct SVG updates, use label instead
        label = _LABELS[self.target_status]
        GLib.idle_add(lambda: self.indicator.set_label(label, ""))

        if progress >= 1.0:
            self.current_status = self.target_status
            self.animation_active = False

    def _update_status(self):
        """Poll DB and update indicator with animation."""
        while self.running:
            status = _detect_status(self.db_path)
            if status != self.target_status:
                self._animate_to_status(status)

            self._update_animation()
            time.sleep(0.05)  # 50ms update rate for smooth animation

    def _clean_zombies(self, widget=None):
        """Hard reset memory and zombies via clean-zombies.py."""
        script = Path(__file__).parent.parent.parent.parent.parent / "scripts" / "clean-zombies.py"
        if script.exists():
            subprocess.Popen([sys.executable, str(script)])
            print("Cleanup script executed.")
        else:
            print("Cleanup script not found.")

    def _init_indicator(self):
        """Initialize AppIndicator."""
        # Use custom icon from ~/.local/share/mnemostroma/icons/
        icon_path = str(Path.home() / ".local/share/mnemostroma/icons/mnemostroma-memory")
        self.indicator = appindicator.Indicator.new(
            "mnemostroma-memory",
            icon_path,
            appindicator.IndicatorCategory.APPLICATION_STATUS
        )
        self.indicator.set_status(appindicator.IndicatorStatus.ACTIVE)

        # Create menu
        menu = Gtk.Menu()

        item_status = Gtk.MenuItem(label="Status")
        item_status.connect("activate", self._show_status)
        menu.append(item_status)

        item_watch = Gtk.MenuItem(label="Open Watch")
        item_watch.connect("activate", self._open_watch)
        menu.append(item_watch)

        item_restart = Gtk.MenuItem(label="Restart Daemon")
        item_restart.connect("activate", self._restart_daemon)
        menu.append(item_restart)

        item_clean = Gtk.MenuItem(label="Hard RAM Reset (Emergency)")
        item_clean.connect("activate", self._clean_zombies)
        menu.append(item_clean)

        menu.append(Gtk.SeparatorMenuItem())

        item_quit = Gtk.MenuItem(label="Quit")
        item_quit.connect("activate", self._quit)
        menu.append(item_quit)

        menu.show_all()
        self.indicator.set_menu(menu)

        # Initial status
        status = _detect_status(self.db_path)
        self.current_status = status
        self.target_status = status
        self.indicator.set_label(_LABELS[status], "")

        # Start polling thread
        t = threading.Thread(target=self._update_status, daemon=True)
        t.start()

    def _quit(self, widget=None):
        """Quit application."""
        self.running = False
        Gtk.main_quit()

    def run(self):
        """Run the tray application."""
        Gtk.main()


def run_tray(db_path: Path, interval: int = 3):
    """Start the system tray icon. Blocks until user quits.

    Tries implementations in order: AppIndicator3 → PyQt6 → pystray.
    """
    if HAS_APPINDICATOR:
        try:
            app = DaemonTrayApp(db_path)
            app.run()
            return
        except Exception as e:
            print(f"AppIndicator3 failed: {e}")

    # Fallback to PyQt6
    try:
        from .tray_pyqt import run_tray as run_pyqt
        run_pyqt(db_path, interval)
        return
    except (ImportError, Exception) as e:
        print(f"PyQt6 fallback failed: {e}")

    # Fallback to pystray
    try:
        from .tray_old_pystray import run_tray as run_pystray
        run_pystray(db_path, interval)
        return
    except (ImportError, Exception) as e:
        print(f"pystray fallback failed: {e}")

    # All failed
    raise ImportError("No tray implementation available (tried AppIndicator3, PyQt6, pystray). "
                      "Run: sudo apt install python3-gi gir1.2-appindicator3-0.1")
