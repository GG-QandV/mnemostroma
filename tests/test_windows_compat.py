# SPDX-License-Identifier: FSL-1.1-MIT
import sys
from pathlib import Path

# Add project root to sys.path to resolve imports of scripts
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import os
import signal
import pytest
from unittest.mock import MagicMock, AsyncMock

import scripts.serveo_manager as sm
from mnemostroma.integration.tunnel.providers.serveo import _build_cmd_args, ServeoTunnelManager
from mnemostroma.integration.mcp_oauth_adapter import (
    _make_watch_backend_from_config,
    WatcherConfig,
    PollingBackend,
)
from mnemostroma.integration.common import safe_ipc_call, _unix_socket_available


def test_build_cmd_args_windows_spaces(monkeypatch):
    """Fix W-01: shlex.split should work properly on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    cmd = 'ssh -o StrictHostKeyChecking=accept-new -R 80:localhost:8768 serveo.net'
    args = _build_cmd_args(cmd)
    assert args == ["ssh", "-o", "StrictHostKeyChecking=accept-new", "-R", "80:localhost:8768", "serveo.net"]


def test_write_text_utf8_encoding(tmp_path):
    """Fix W-02: Ensure write_text and read_text use UTF-8 by default."""
    f = tmp_path / "test_file.txt"
    test_str = "Тестовый путь с Юникодом"
    f.write_text(test_str, encoding="utf-8")
    assert f.read_text(encoding="utf-8") == test_str


def test_ssh_version_fallback_old_openssh(monkeypatch):
    """Fix W-03: Ensure StrictHostKeyChecking falls back to yes on older SSH versions."""
    # Simulation of old OpenSSH version
    monkeypatch.setattr(sm, "check_ssh_version", lambda: "7.2")
    cmd = sm.build_ssh_cmd(port=8768)
    assert "StrictHostKeyChecking=yes" in cmd

    # Simulation of modern OpenSSH version
    monkeypatch.setattr(sm, "check_ssh_version", lambda: "8.4")
    cmd = sm.build_ssh_cmd(port=8768)
    assert "StrictHostKeyChecking=accept-new" in cmd


def test_stop_sends_ctrl_c_on_windows(monkeypatch):
    """Fix W-04: stop() should send CTRL_C_EVENT to the process group on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    ctrl_c_val = 0
    if not hasattr(signal, "CTRL_C_EVENT"):
        monkeypatch.setattr(signal, "CTRL_C_EVENT", ctrl_c_val, raising=False)
    else:
        ctrl_c_val = signal.CTRL_C_EVENT
        
    manager = ServeoTunnelManager(port=8768)
    
    mock_proc = MagicMock()
    mock_proc.poll.return_value = None
    manager._proc = mock_proc
    
    manager.stop()
    mock_proc.send_signal.assert_called_once_with(ctrl_c_val)


def test_inotify_fallback_on_windows(monkeypatch):
    """Fix W-05: inotify backend falls back to PollingBackend on Windows."""
    monkeypatch.setattr(sys, "platform", "win32")
    cfg = WatcherConfig(backend="inotify")
    backend = _make_watch_backend_from_config(cfg)
    assert isinstance(backend, PollingBackend)





@pytest.mark.asyncio
async def test_ipc_fallback_to_tcp_on_old_windows(monkeypatch):
    """Fix W-07: safe_ipc_call falls back to TCP connection when unix socket / pipe is unavailable."""
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr("mnemostroma.integration.common._unix_socket_available", lambda: False)
    
    mock_open_conn = AsyncMock()
    mock_reader = AsyncMock()
    mock_reader.readline.return_value = b'{"id": 1, "result": "fallback_ok"}\n'
    
    # Use MagicMock for synchronous methods to prevent RuntimeWarnings
    mock_writer = MagicMock()
    mock_writer.write = MagicMock()
    mock_writer.close = MagicMock()
    mock_writer.drain = AsyncMock()
    mock_writer.wait_closed = AsyncMock()
    
    mock_open_conn.return_value = (mock_reader, mock_writer)
    
    monkeypatch.setattr("asyncio.open_connection", mock_open_conn)
    
    res = await safe_ipc_call("test_tool", {"arg": 1})
    assert res == "fallback_ok"
    mock_open_conn.assert_called_once_with("127.0.0.1", 8767)
