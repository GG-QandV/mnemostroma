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
import logging
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon, QMenu
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt6.QtCore import QTimer, QSize

from mnemostroma.integration.tunnel.state import get_tunnel_url, get_tunnel_token
from mnemostroma.integration.tunnel.ui_meta import get_meta

logger = logging.getLogger("mnemostroma.tray")


def _copy(text: str) -> None:
    try:
        QApplication.clipboard().setText(text)
    except Exception as e:
        logger.warning("clipboard copy failed: %s", e)


def _run_tunnel(action: str) -> None:
    from mnemostroma.integration.tunnel.resolve import resolve_mnemostroma_executable
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kwargs["start_new_session"] = True
    try:
        cmd = resolve_mnemostroma_executable() + ["tunnel", action]
        subprocess.Popen(cmd, **kwargs)
    except Exception as e:
        logger.error("Failed to run tunnel action %s: %s", action, e)


class TunnelUrlWatcher:
    """
    Следит за изменением tunnel_url. Интегрируется в существующий QTimer (_check_status).
    При появлении нового URL показывает balloon-уведомление через tray_icon.
    """

    def __init__(self, tray_icon: QSystemTrayIcon) -> None:
        self._tray     = tray_icon
        self._last_url = get_tunnel_url()

    def check(self) -> None:
        current = get_tunnel_url()
        if current and current != self._last_url:
            self._last_url = current
            self._notify(current)
        elif not current and self._last_url is not None:
            self._last_url = None

    def _notify(self, url: str) -> None:
        short = url.replace("https://", "")[:50]
        self._tray.showMessage(
            "🌐 Tunnel Ready",
            f"Open Tray → Tunnel to copy per-chat URLs\n{short}",
            QSystemTrayIcon.MessageIcon.Information,
            6000,
        )

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
    _ST_PROCESSING: "Mnemostroma: Active / Processing [Активен]",
    _ST_CONNECTED: "Mnemostroma: Recent Activity [Недавняя активность]",
    _ST_IDLE: "Mnemostroma: Ready / Waiting [Ожидание]",
    _ST_WARNING: "Mnemostroma: System Warning [Внимание]",
    _ST_ERROR: "Mnemostroma: Offline or Error [Ошибка]",
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
        self._tunnel_watcher = TunnelUrlWatcher(self.tray_icon)

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
        if hasattr(self, "_tunnel_watcher"):
            self._tunnel_watcher.check()

    def _open_watch(self):
        """Open 'mnemostroma watch' in new terminal."""
        import shlex
        try:
            # Use current interpreter to be sure it's available and has mnemostroma
            python_bin = sys.executable
            cmd = f"{shlex.quote(python_bin)} -m mnemostroma watch"

            # Try common terminal emulators
            terminals = [
                ["gnome-terminal", "--", "bash", "-c", f"{cmd}; exec bash"],
                ["tilix", "--", "bash", "-c", f"{cmd}; exec bash"],
                ["konsole", "--", "bash", "-c", f"{cmd}; exec bash"],
                ["xfce4-terminal", "-e", f"bash -c '{cmd}; exec bash'"],
                ["xterm", "-e", f"bash -c '{cmd}; exec bash'"],
            ]
            for term_cmd in terminals:
                try:
                    subprocess.Popen(term_cmd)
                    return
                except FileNotFoundError:
                    continue
            print(f"No terminal found. Run manually: {cmd}")
        except Exception as e:
            print(f"Error opening watch: {e}")

    def _restart_daemon(self):
        """Restart Mnemostroma services in a cascade."""
        try:
            from mnemostroma.tools.cleanup import stop_services, start_services
            # Run cascade restart in a background thread to prevent UI lockup
            def run_restart():
                try:
                    stop_services()
                    time.sleep(1.0)
                    start_services()
                    print("All services restarted in cascade.")
                except Exception as e:
                    print(f"Error in cascade restart thread: {e}")

            thread = threading.Thread(target=run_restart)
            thread.daemon = True
            thread.start()
            print("Restart cascade thread started.")
        except Exception as e:
            print(f"Error starting restart cascade thread: {e}")

    def _show_status(self):
        """Show status in tray balloon."""
        status = self.current_status
        self.tray_icon.showMessage(
            "Mnemostroma Status",
            _LABELS[status],
            QSystemTrayIcon.MessageIcon.Information,
            5000
        )

    def _clean_zombies(self):
        """Hard reset memory and zombies via integrated cleanup module."""
        try:
            from mnemostroma.tools.cleanup import emergency_cleanup
            # Run cleanup in a background thread to prevent UI lockup
            thread = threading.Thread(target=emergency_cleanup, args=(True,))
            thread.daemon = True
            thread.start()
            print("Background emergency cleanup thread started.")
        except Exception as e:
            print(f"Failed to start cleanup thread: {e}")

    def _populate_tunnel_submenu(self) -> None:
        """Пересобирает tunnel submenu при каждом открытии (aboutToShow — нет кэша)."""
        self._tunnel_submenu.clear()

        url   = get_tunnel_url()
        token = get_tunnel_token()

        if url:
            short = url.replace("https://", "").replace("http://", "")[:40]
            s = self._tunnel_submenu.addAction(f"● {short}")
            s.setEnabled(False)
            self._tunnel_submenu.addSeparator()

            try:
                from mnemostroma.integration.mcp_oauth_adapter import load_route_config
                routes = load_route_config().routes
            except Exception as e:
                logger.warning("tray tunnel menu: failed to load routes.json: %s", e)
                routes = {}

            for path, route_cfg in routes.items():
                client = route_cfg.get("client", "")
                if not client:
                    continue

                meta      = get_meta(client)
                full_url  = f"{url}{path}"
                auth_list = route_cfg.get("auth", [])
                show_tok  = meta["needs_token"] and "bearer" in auth_list and token is not None

                sub = self._tunnel_submenu.addMenu(f"{meta['icon']} {meta['label']}")

                act_url = sub.addAction("📋 Copy URL")
                act_url.triggered.connect(lambda checked, v=full_url: _copy(v))

                if show_tok:
                    act_tok = sub.addAction("📋 Copy Token")
                    act_tok.triggered.connect(lambda checked, t=token: _copy(t))

                hint_action = sub.addAction(meta["hint"])
                hint_action.setEnabled(False)

            self._tunnel_submenu.addSeparator()
            stop = self._tunnel_submenu.addAction("⏹  Stop Tunnel")
            stop.triggered.connect(self._stop_tunnel_with_feedback)

        else:
            start = self._tunnel_submenu.addAction("▶  Start Tunnel")
            start.triggered.connect(lambda: _run_tunnel("start"))

            info = QMenu("ℹ️ After start:", self._tunnel_submenu)
            for label in ["Perplexity (no auth)", "Claude.ai / ChatGPT (OAuth)", "Grok (Bearer token)"]:
                a = info.addAction(label)
                a.setEnabled(False)
            self._tunnel_submenu.addMenu(info)

    def _stop_tunnel_with_feedback(self) -> None:
        _run_tunnel("stop")
        self.tray_icon.showMessage(
            "Tunnel",
            "Stopping tunnel…",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
        QTimer.singleShot(2500, self._populate_tunnel_submenu)

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
        menu.addAction("Hard RAM Reset (Emergency)", self._clean_zombies)
        menu.addSeparator()

        self._tunnel_submenu = QMenu("🌐 Tunnel")
        self._tunnel_submenu.aboutToShow.connect(self._populate_tunnel_submenu)
        menu.addMenu(self._tunnel_submenu)

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


def check_pyqt6() -> bool:
    """Check if PyQt6 is available, otherwise print helpful error."""
    try:
        from PyQt6.QtWidgets import QApplication
        return True
    except ImportError:
        raise ImportError("PyQt6 not installed. Run: pip install 'mnemostroma[tray]'")

def run_tray(db_path: Path, interval: int = 3):
    """Start the system tray icon. Blocks until user quits."""
    check_pyqt6()

    from PyQt6.QtWidgets import QApplication
    app = DaemonTrayApp(sys.argv, db_path)
    sys.exit(app.exec())

if __name__ == "__main__":
    db = Path.home() / ".mnemostroma" / "logs.db"
    run_tray(db)
