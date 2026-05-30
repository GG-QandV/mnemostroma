# SPDX-License-Identifier: FSL-1.1-MIT
import os
import sys
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from mnemostroma.integration.tunnel.resolve import (
    resolve_mnemostroma_executable,
    resolve_cloudflared_executable,
    _is_headless,
)


def test_resolve_mnemostroma_uses_sys_executable():
    res = resolve_mnemostroma_executable()
    assert res == [sys.executable, "-m", "mnemostroma"]


def test_resolve_cloudflared_prefers_local_bin(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    
    bin_dir = tmp_path / ".mnemostroma" / "bin"
    bin_dir.mkdir(parents=True)
    
    cf_file = bin_dir / ("cloudflared.exe" if sys.platform == "win32" else "cloudflared")
    cf_file.write_text("fake binary")
    
    path = resolve_cloudflared_executable()
    assert path == str(cf_file)


def test_resolve_cloudflared_falls_back_to_shutil_which(monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: Path("/nonexistent"))
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/cloudflared")
    
    path = resolve_cloudflared_executable()
    assert path == "/usr/bin/cloudflared"


def test_is_headless_cases(monkeypatch):
    # Case 1: no stdin or stdin is not a tty
    monkeypatch.setattr(sys, "stdin", None)
    assert _is_headless() is True
    
    # Case 2: stdin is a mock non-tty
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = False
    monkeypatch.setattr(sys, "stdin", mock_stdin)
    assert _is_headless() is True
    
    # Case 3: stdin is tty, win32 headless via SESSIONNAME
    mock_stdin.isatty.return_value = True
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("SESSIONNAME", "")
    assert _is_headless() is True
    
    monkeypatch.setenv("SESSIONNAME", "Console")
    assert _is_headless() is False
    
    # Case 4: stdin is tty, linux headless via DISPLAY
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", "")
    assert _is_headless() is True
    
    monkeypatch.setenv("DISPLAY", ":0")
    assert _is_headless() is False
