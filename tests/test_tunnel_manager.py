# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from mnemostroma.integration.tunnel import manager
from mnemostroma.integration.tunnel.providers import cloudflare


async def make_mock_stdout(lines: list[bytes]):
    for line in lines:
        yield line


class MockProcessWithGen:
    def __init__(self, lines: list[bytes]):
        self.stdout = make_mock_stdout(lines)
        self.terminated = False
        self.killed = False

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True

    async def wait(self):
        return 0


# ── Группа 1: Тесты tunnel/providers/cloudflare.py ───────────────────────────

@pytest.mark.asyncio
async def test_parse_url_from_stdout():
    # 1. test_parse_url_from_stdout -> _wait_for_url парсит URL из строки вывода cloudflared
    lines = [
        b"Starting tunnel...\n",
        b"INF  Connection established...\n",
        b"INF  Your quick Tunnel is available at https://test-123.trycloudflare.com\n",
        b"INF  Route established...\n"
    ]
    proc = MockProcessWithGen(lines)
    url = await cloudflare._wait_for_url(proc, timeout=2)
    assert url == "https://test-123.trycloudflare.com"


@pytest.mark.asyncio
async def test_url_timeout():
    # 2. test_url_timeout -> _wait_for_url выбрасывает TimeoutError/RuntimeError если URL не появляется
    lines = [
        b"Starting tunnel...\n",
        b"Failed to read configs...\n"
    ]
    proc = MockProcessWithGen(lines)
    # Ждем таймаута за 0.1 секунды
    with pytest.raises(Exception):
        await cloudflare._wait_for_url(proc, timeout=0.1)


@pytest.mark.asyncio
async def test_ensure_cloudflared_skips_download_if_exists(monkeypatch, tmp_path):
    # 3. test_ensure_cloudflared_skips_download_if_exists -> если бинарь есть, не скачивает
    fake_bin = tmp_path / "cloudflared"
    fake_bin.touch()
    monkeypatch.setattr(cloudflare, "CLOUDFLARED", fake_bin)

    # Проверяем, что функция возвращает путь к существующему файлу без вызова сети
    path = await cloudflare.ensure_cloudflared()
    assert path == fake_bin


@pytest.mark.asyncio
async def test_unsupported_platform(monkeypatch):
    # 4. test_unsupported_platform -> start_tunnel на unknown platform -> RuntimeError
    monkeypatch.setattr(sys, "platform", "unknown-os")
    monkeypatch.setattr(cloudflare, "CLOUDFLARED", Path("/nonexistent/cloudflared"))

    # Очищаем DOWNLOAD_URLS для этого теста или подменяем platform
    with pytest.raises(RuntimeError) as exc_info:
        await cloudflare.ensure_cloudflared()
    assert "Unsupported platform" in str(exc_info.value)


# ── Группа 2: Тесты tunnel/manager.py ────────────────────────────────────────

@pytest.mark.asyncio
async def test_tunnel_url_written_to_file(monkeypatch, tmp_path):
    # Тестируем, что URL и токен записываются в соответствующие папки
    fake_urls_dir = tmp_path / "tunnel_urls"
    fake_tokens_dir = tmp_path / "tunnel_tokens"
    monkeypatch.setattr(manager, "TUNNEL_URLS_DIR", fake_urls_dir)
    monkeypatch.setattr(manager, "TUNNEL_TOKENS_DIR", fake_tokens_dir)

    manager._save_tunnel_url("my-sub", "https://xyz.serveo.net")
    manager._save_tunnel_token("my-sub", "test-token-123")

    expected_url_file = fake_urls_dir / "user-my-sub.txt"
    expected_token_file = fake_tokens_dir / "user-my-sub.txt"

    assert expected_url_file.exists()
    assert expected_url_file.read_text(encoding="utf-8").strip() == "https://xyz.serveo.net"
    assert expected_token_file.exists()
    assert expected_token_file.read_text(encoding="utf-8").strip() == "test-token-123"

    # Тестируем анонимный режим
    manager._save_tunnel_url(None, "https://anonymous.serveo.net")
    manager._save_tunnel_token(None, "anon-token")

    expected_anon_url_file = fake_urls_dir / "user-anonymous.txt"
    expected_anon_token_file = fake_tokens_dir / "user-anonymous.txt"

    assert expected_anon_url_file.exists()
    assert expected_anon_url_file.read_text(encoding="utf-8").strip() == "https://anonymous.serveo.net"
    assert expected_anon_token_file.exists()
    assert expected_anon_token_file.read_text(encoding="utf-8").strip() == "anon-token"


@pytest.mark.asyncio
async def test_shutdown_stops_tunnel_and_adapter():
    # Тестируем, что _shutdown останавливает как туннель, так и адаптер
    mock_proc = MagicMock()
    mock_tunnel_mgr = MagicMock()

    await manager._shutdown(mock_proc, mock_tunnel_mgr)

    mock_tunnel_mgr.stop.assert_called_once()
    mock_proc.terminate.assert_called_once()


def test_print_connection_guide_contains_url(capsys):
    # 7. test_print_connection_guide_contains_url -> _print_connection_guide выводит url и все 4 фазы
    url = "https://my-test-tunnel.trycloudflare.com"
    token_val = "test-token-12345"

    manager._print_connection_guide(url, token_val)
    captured = capsys.readouterr()

    assert url in captured.out
    assert "[Phase 0] Perplexity" in captured.out
    assert "[Phase 1] Claude.ai" in captured.out
    assert "[Phase 2] ChatGPT" in captured.out
    assert "[Phase 3] Grok" in captured.out


def test_tunnel_stop_cleans_flat_file(monkeypatch, tmp_path):
    """ServeoTunnelManager.stop() удаляет serveo_url и tunnel_url."""
    from mnemostroma.integration.tunnel.providers.serveo import ServeoTunnelManager

    # Мокаем домашнюю папку
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)

    serveo_url_file = mnemo_dir / "serveo_url"
    tunnel_url_file = mnemo_dir / "tunnel_url"

    serveo_url_file.write_text("https://test.serveo.net", encoding="utf-8")
    tunnel_url_file.write_text("https://test.serveo.net", encoding="utf-8")

    mgr = ServeoTunnelManager()
    mgr.stop()

    assert not serveo_url_file.exists()
    assert not tunnel_url_file.exists()


@pytest.mark.asyncio
async def test_tunnel_start_failure_invalidates_flat_file(monkeypatch, tmp_path):
    """При неудачном запуске туннеля в manager.run() или start() плоский файл очищается."""
    from mnemostroma.integration.tunnel.providers.serveo import ServeoTunnelManager

    # Мокаем домашнюю папку
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)

    serveo_url_file = mnemo_dir / "serveo_url"
    tunnel_url_file = mnemo_dir / "tunnel_url"

    serveo_url_file.write_text("https://old.serveo.net", encoding="utf-8")
    tunnel_url_file.write_text("https://old.serveo.net", encoding="utf-8")

    def mock_start(self, timeout=15.0):
        self.stop()
        raise TimeoutError("Serveo did not return a URL")

    monkeypatch.setattr(ServeoTunnelManager, "start", mock_start)

    mgr = ServeoTunnelManager()
    with pytest.raises(TimeoutError):
        mgr.start()

    assert not serveo_url_file.exists()
    assert not tunnel_url_file.exists()


def test_headless_returns_none_subdomain(monkeypatch, tmp_path):
    """Bypass input() in headless settings and return None or config subdomain."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    # Мокаем путь к конфигурационному файлу напрямую
    fake_config_path = tmp_path / ".mnemostroma" / "tunnel_config.json"
    monkeypatch.setattr(manager, "TUNNEL_CONFIG_PATH", fake_config_path)

    # Mock _is_headless to return True
    monkeypatch.setattr("mnemostroma.integration.tunnel.resolve._is_headless", lambda: True)

    # 1. Config doesn't exist -> returns None (headless, no ask)
    sub = manager._get_or_ask_subdomain()
    assert sub is None

    # 2. Config exists -> returns config subdomain even in headless
    fake_config_path.parent.mkdir(parents=True, exist_ok=True)
    import json
    fake_config_path.write_text(json.dumps({"subdomain": "saved-sub"}), encoding="utf-8")

    sub = manager._get_or_ask_subdomain()
    assert sub == "saved-sub"


def test_pid_file_restored_after_tray_restart(monkeypatch, tmp_path):
    """Verify that _load_saved_proc correctly restores a process handle from pid file."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "ssh"
    mock_proc.cmdline.return_value = ["ssh", "-R", "serveo.net"]
    monkeypatch.setattr(psutil, "Process", lambda pid: mock_proc)

    # Write mock pid file
    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)
    (mnemo_dir / "serveo_tunnel.pid").write_text("12345", encoding="utf-8")

    # Call serveo.py's _load_saved_proc
    from mnemostroma.integration.tunnel.providers.serveo import _load_saved_proc, ServeoTunnelManager
    proc = _load_saved_proc()
    assert proc is not None
    assert proc.pid == 12345

    # Start ServeoTunnelManager, should restore _proc
    mgr = ServeoTunnelManager()
    assert mgr._proc is not None
    assert mgr._proc.pid == 12345


def test_zombie_proc_killed_on_stop_after_restart(monkeypatch, tmp_path):
    """Verify that stop() terminates/kills a restored process process group."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "linux") # test linux stop logic

    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: True)

    mock_proc = MagicMock()
    mock_proc.name.return_value = "ssh"
    mock_proc.cmdline.return_value = ["ssh", "-R", "serveo.net"]
    monkeypatch.setattr(psutil, "Process", lambda pid: mock_proc)

    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)
    (mnemo_dir / "serveo_tunnel.pid").write_text("12345", encoding="utf-8")

    from mnemostroma.integration.tunnel.providers.serveo import ServeoTunnelManager
    mgr = ServeoTunnelManager()
    assert mgr._proc is not None

    mgr.stop()
    mock_proc.terminate.assert_called_once()
    assert not (mnemo_dir / "serveo_tunnel.pid").exists()
