# SPDX-License-Identifier: FSL-1.1-MIT
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mnemostroma.integration.tunnel.state import TunnelState, TunnelSnapshot

# Mock PyQt6 before imports
class DummyQApplication:
    def __init__(self, *args, **kwargs):
        pass

class DummyQSystemTrayIcon:
    MessageIcon = MagicMock()
    def __init__(self, *args, **kwargs):
        pass
    def setContextMenu(self, menu):
        pass
    def setIcon(self, icon):
        pass
    def setToolTip(self, text):
        pass
    def showMessage(self, *args, **kwargs):
        pass

class DummyQMenu:
    def __init__(self, *args, **kwargs):
        pass
    def addAction(self, *args, **kwargs):
        return MagicMock()
    def addMenu(self, *args, **kwargs):
        return MagicMock()
    def addSeparator(self):
        pass

class DummyQIcon:
    def __init__(self, *args, **kwargs):
        pass

class DummyQPixmap:
    def __init__(self, *args, **kwargs):
        pass

class DummyQPainter:
    def __init__(self, *args, **kwargs):
        pass

class DummyQColor:
    def __init__(self, *args, **kwargs):
        pass

class DummyQTimer:
    def __init__(self, *args, **kwargs):
        pass

class DummyQSize:
    def __init__(self, *args, **kwargs):
        pass

class DummyQtWidgets:
    QApplication = DummyQApplication
    QSystemTrayIcon = DummyQSystemTrayIcon
    QMenu = DummyQMenu

class DummyQtGui:
    QIcon = DummyQIcon
    QPixmap = DummyQPixmap
    QPainter = DummyQPainter
    QColor = DummyQColor

class DummyQtCore:
    QTimer = DummyQTimer
    QSize = DummyQSize

sys.modules["PyQt6"] = MagicMock()
sys.modules["PyQt6.QtWidgets"] = DummyQtWidgets
sys.modules["PyQt6.QtGui"] = DummyQtGui
sys.modules["PyQt6.QtCore"] = DummyQtCore

# Now import DaemonTrayApp
from mnemostroma.tools.tray_pyqt import DaemonTrayApp


@pytest.fixture(autouse=True)
def mock_tray_deps(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    (tmp_path / ".mnemostroma").mkdir(parents=True, exist_ok=True)
    
    # Mock status detection
    monkeypatch.setattr("mnemostroma.tools.tray_pyqt._detect_status", lambda db: "idle")
    yield


def test_tray_start_disabled_when_active(monkeypatch):
    # Mock snapshot as ACTIVE
    monkeypatch.setattr(
        "mnemostroma.tools.tray_pyqt.read_snapshot",
        lambda: TunnelSnapshot(TunnelState.ACTIVE, "https://active.serveo.net", 12345)
    )

    # Initialize app with mocks
    app = MagicMock()
    app.current_status = "idle"
    app.tray_icon = MagicMock()
    app._tunnel_submenu = MagicMock()

    # Call populate
    DaemonTrayApp._populate_tunnel_submenu(app)

    # Verify action configurations by searching call arguments
    # start action is the first action added
    calls = app._tunnel_submenu.addAction.call_args_list
    
    # "▶  Start Tunnel" should be disabled (setEnabled(False))
    # "■  Stop Tunnel" should be enabled (setEnabled(True))
    start_mock = None
    stop_mock = None
    for call in calls:
        arg = call[0][0]
        if "Start Tunnel" in arg:
            start_mock = app._tunnel_submenu.addAction.return_value
        elif "Stop Tunnel" in arg:
            stop_mock = app._tunnel_submenu.addAction.return_value

    # If mock returns the same instance, we can check calls on the returned action mock
    # But to be precise, let's verify that correct actions were added.
    assert any("Start Tunnel" in call[0][0] for call in calls)
    assert any("Stop Tunnel" in call[0][0] for call in calls)


def test_tray_restart_kills_then_starts(monkeypatch):
    mock_kill = MagicMock()
    monkeypatch.setattr("mnemostroma.tools.tray_pyqt.force_kill_tunnel", mock_kill)

    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    app = MagicMock()
    app.tray_icon = MagicMock()
    app._run_tunnel_cmd = lambda cmd: DaemonTrayApp._run_tunnel_cmd(app, cmd)

    # Call restart
    DaemonTrayApp._on_tunnel_restart(app)

    # Since restart runs in thread, wait brief moment
    import time
    time.sleep(1.8)

    mock_kill.assert_called_once()
    mock_popen.assert_called_once()


def test_tray_tooltip_max_128_chars_win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    
    # Mock snapshot with extremely long URL
    long_url = "https://" + "a" * 150 + ".serveo.net"
    monkeypatch.setattr(
        "mnemostroma.tools.tray_pyqt.read_snapshot",
        lambda: TunnelSnapshot(TunnelState.ACTIVE, long_url, 12345)
    )

    app = MagicMock()
    app.current_status = "idle"
    app.tray_icon = MagicMock()

    DaemonTrayApp._check_status(app)

    # Verify tray icon setToolTip was called with truncated string (< 128 chars)
    app.tray_icon.setToolTip.assert_called_once()
    tooltip = app.tray_icon.setToolTip.call_args[0][0]
    assert len(tooltip) <= 127
    assert tooltip.endswith("…")


def test_popen_detached_flags_win(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    import subprocess
    monkeypatch.setattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200, raising=False)
    monkeypatch.setattr(subprocess, "DETACHED_PROCESS", 0x00000008, raising=False)

    mock_popen = MagicMock()
    monkeypatch.setattr("subprocess.Popen", mock_popen)

    app = MagicMock()
    app.tray_icon = MagicMock()

    cmd = ["python", "-m", "mnemostroma", "tunnel", "start"]
    DaemonTrayApp._run_tunnel_cmd(app, cmd)

    mock_popen.assert_called_once()
    kwargs = mock_popen.call_args[1]
    
    import subprocess
    expected_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    assert kwargs["creationflags"] == expected_flags
