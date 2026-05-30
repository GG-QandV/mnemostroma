# SPDX-License-Identifier: FSL-1.1-MIT
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from mnemostroma.integration.tunnel.state import (
    TunnelState,
    read_snapshot,
    force_kill_tunnel,
    _get_base
)

@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)

    import mnemostroma.integration.tunnel.state as state
    monkeypatch.setattr(state, "_BASE", mnemo_dir)
    monkeypatch.setattr(state, "_URL_FILE", mnemo_dir / "tunnel_url")
    monkeypatch.setattr(state, "_PID_FILE", mnemo_dir / "serveo_tunnel.pid")
    yield


def test_read_snapshot_dead_initially():
    snap = read_snapshot()
    assert snap.state == TunnelState.DEAD
    assert snap.url is None
    assert snap.pid is None


def test_read_snapshot_active(monkeypatch, tmp_path):
    mnemo_dir = tmp_path / ".mnemostroma"
    pid_file = mnemo_dir / "serveo_tunnel.pid"
    url_file = mnemo_dir / "tunnel_url"

    pid_file.write_text("12345", encoding="utf-8")
    url_file.write_text("https://my-tunnel.serveo.net", encoding="utf-8")

    # Mock psutil
    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 12345)

    snap = read_snapshot()
    assert snap.state == TunnelState.ACTIVE
    assert snap.url == "https://my-tunnel.serveo.net"
    assert snap.pid == 12345


def test_read_snapshot_stale(monkeypatch, tmp_path):
    mnemo_dir = tmp_path / ".mnemostroma"
    pid_file = mnemo_dir / "serveo_tunnel.pid"

    pid_file.write_text("12345", encoding="utf-8")

    # Mock psutil
    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 12345)

    snap = read_snapshot()
    assert snap.state == TunnelState.STALE
    assert snap.url is None
    assert snap.pid == 12345


def test_read_snapshot_dead_cleanup(monkeypatch, tmp_path):
    mnemo_dir = tmp_path / ".mnemostroma"
    pid_file = mnemo_dir / "serveo_tunnel.pid"
    url_file = mnemo_dir / "tunnel_url"

    pid_file.write_text("12345", encoding="utf-8")
    url_file.write_text("https://my-tunnel.serveo.net", encoding="utf-8")

    # Mock psutil to return False (process is dead)
    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: False)

    snap = read_snapshot()
    assert snap.state == TunnelState.DEAD
    assert snap.url is None
    assert snap.pid is None

    # Проверяем, что файлы были очищены
    assert not pid_file.exists()
    assert not url_file.exists()


def test_force_kill_via_taskkill(monkeypatch, tmp_path):
    mnemo_dir = tmp_path / ".mnemostroma"
    pid_file = mnemo_dir / "serveo_tunnel.pid"
    pid_file.write_text("12345", encoding="utf-8")

    # Mock platforms and psutil
    monkeypatch.setattr(sys, "platform", "win32")
    
    import mnemostroma.integration.tunnel.state as state
    monkeypatch.setattr(state, "_PSUTIL", False)
    
    import os
    monkeypatch.setattr(os, "kill", lambda pid, sig: None)

    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    killed = force_kill_tunnel()
    assert killed is True
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "taskkill" in args
    assert "12345" in args
    assert not pid_file.exists()


def test_base_path_uses_userprofile_on_win(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "win_profile"))
    
    base = _get_base()
    assert base == tmp_path / "win_profile" / ".mnemostroma"
