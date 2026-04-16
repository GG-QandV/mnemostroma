# SPDX-License-Identifier: FSL-1.1-MIT
"""mnemostroma tray — PyQt6 system tray with working menu.

Floating coloured circle in the OS taskbar/tray that reflects
the live health of the Mnemostroma daemon.

Colour legend:
  Blue   #4A90D9  — idle / waiting (no activity >30s)
  Teal   #00ACC1  — connected / recent (activity 5–30s ago)
  Green  #66BB6A  — processing (activity in last 5s)
  Yellow #FFC107  — warning (WARNING-level log in last 60s)
  Red    #E53935  — error / daemon not responding
"""
import json
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import QTimer, QSize

# ── Status constants ────────────────────────────────────────────
_ST_PROCESSING = "processing"
_ST_CONNECTED = "connected"
_ST_IDLE = "idle"
_ST_WARNING = "warning"
_ST_ERROR = "error"

_COLOURS = {
    _ST_PROCESSING: "#66BB6A",  # green  — active right now
    _ST_CONNECTED: "#00ACC1",   # teal   — connected, idle
    _ST_IDLE: "#4A90D9",        # blue   — waiting
    _ST_WARNING: "#FFC107",     # yellow — warnings
    _ST_ERROR: "#E53935",       # red    — error
}

_LABELS = {
    _ST_PROCESSING: "Mnemostroma: processing",
    _ST_CONNECTED: "Mnemostroma: connected",
    _ST_IDLE: "Mnemostroma: idle",
    _ST_WARNING: "Mnemostroma: warning",
    _ST_ERROR: "Mnemostroma: error / not running",
}

_SIZE = 64   # icon canvas size in px
_R = 28      # circle radius
_DAEMON_SOCK = Path.home() / ".mnemostroma" / "daemon.sock"
_CONFIG_PATH = Path.home() / ".mnemostroma" / "config.json"


def _make_icon(status: str) -> QIcon:
    """Draw a coloured circle with shadow using QPainter."""
    pixmap = QPixmap(QSize(_SIZE, _SIZE))
    pixmap.fill(QColor("transparent"))

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    cx, cy = _SIZE // 2, _SIZE // 2
    color_hex = _COLOURS.get(status, _COLOURS[_ST_IDLE])

    # Shadow
    shadow_color = QColor(0, 0, 0, 60)
    painter.setBrush(shadow_color)
    painter.setPen(QColor("transparent"))
    painter.drawEllipse(cx - _R + 2, cy - _R + 2, _R * 2, _R * 2)

    # Main circle
    main_color = QColor(color_hex)
    painter.setBrush(main_color)
    painter.drawEllipse(cx - _R, cy - _R, _R * 2, _R * 2)

    # Highlight
    highlight_color = QColor(255, 255, 255, 90)
    painter.setBrush(highlight_color)
    hw = _R // 3
    painter.drawEllipse(cx - _R + 6, cy - _R + 6, hw, hw)

    painter.end()
    return QIcon(pixmap)


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
        return _ST_IDLE

    except Exception:
        return _ST_ERROR


class DaemonTrayApp(QApplication):
    """PyQt6 system tray application for Mnemostroma."""

    def __init__(self, sys_argv, db_path: Path):
        super().__init__(sys_argv)
        self.db_path = db_path
        self.tray_icon = None
        self.current_status = _ST_IDLE
        self.timer = None
        self._init_tray()

    def _create_icon(self, status: str) -> QIcon:
        """Create icon for current status."""
        return _make_icon(status)

    def _check_status(self):
        """Poll database and update icon."""
        status = _detect_status(self.db_path)
        if status != self.current_status:
            self.current_status = status
            if self.tray_icon:
                self.tray_icon.setIcon(self._create_icon(status))
                self.tray_icon.setToolTip(_LABELS[status])

    def _open_watch(self):
        """Open 'mnemostroma watch' in new terminal."""
        try:
            # Try common terminal emulators
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
            print("No terminal found")
        except Exception as e:
            print(f"Error opening watch: {e}")

    def _restart_daemon(self):
        """Restart mnemostroma daemon."""
        try:
            # Try systemctl first
            subprocess.run(
                ["systemctl", "--user", "restart", "mnemostroma-daemon"],
                check=True,
                timeout=10
            )
            print("Daemon restarted via systemctl")
        except Exception:
            try:
                # Fallback: try direct socket restart
                subprocess.run(
                    ["mnemostroma", "daemon", "restart"],
                    timeout=10
                )
                print("Daemon restarted via mnemostroma command")
            except Exception as e:
                print(f"Error restarting daemon: {e}")

    def _show_status(self):
        """Show status in console."""
        status = self.current_status
        print(f"Mnemostroma Status: {_LABELS[status]}")

    def _init_tray(self):
        """Initialize system tray icon and menu."""
        # Create initial icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self._create_icon(_ST_IDLE))
        self.tray_icon.setToolTip("Mnemostroma: initializing...")

        # Create menu
        menu = QMenu()
        menu.addAction("Status", self._show_status)
        menu.addAction("Open Watch", self._open_watch)
        menu.addAction("Restart Daemon", self._restart_daemon)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)

        self.tray_icon.setContextMenu(menu)
        self.tray_icon.show()

        # Start polling timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._check_status)
        self.timer.start(3000)  # Poll every 3 seconds

        # Initial status check
        self._check_status()


def run_tray(db_path: Path, interval: int = 3):
    """Start the system tray icon. Blocks until user quits."""
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QIcon
    except ImportError as e:
        print(f"PyQt6 not installed. Run: pip install PyQt6")
        return

    app = DaemonTrayApp(sys.argv, db_path)
    sys.exit(app.exec())
