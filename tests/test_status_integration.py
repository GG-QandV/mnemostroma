import pytest
from unittest.mock import patch, MagicMock
import psutil
from mnemostroma.cli import get_daemon_status

# T-09: Daemon запущен Task Scheduler, status вызван из обычного PowerShell
# Симулируем через разные уровни прав psutil
def test_status_running_with_limited_access(monkeypatch, tmp_path):
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("5555", encoding="utf-8")
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path))

    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process") as mock:
        mock.return_value.status.side_effect = psutil.AccessDenied(5555)
        result = get_daemon_status()

    assert result["status"] == "running"
    assert pid_file.exists()   # файл остался

# T-10: Daemon реально остановлен → status=stopped, файл удалён
def test_status_stopped_cleans_pid_file(monkeypatch, tmp_path):
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("5556", encoding="utf-8")
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path))

    with patch("psutil.pid_exists", return_value=False):
        result = get_daemon_status()

    assert result["status"] == "stopped"
    assert not pid_file.exists()

# T-11: PID-файл отсутствует, daemon жив → status=running после восстановления
def test_status_recovers_missing_pid_file(monkeypatch, tmp_path):
    monkeypatch.setenv("MNEMO_DIR", str(tmp_path))
    pid_file = tmp_path / "daemon.pid"
    mock_proc = MagicMock()
    mock_proc.pid = 7777
    mock_proc.info = {"cmdline": ["python", "conductor"]}
    mock_proc.is_running.return_value = True

    with patch("psutil.process_iter", return_value=[mock_proc]), \
         patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process") as mock:
        mock.return_value.status.return_value = psutil.STATUS_RUNNING
        result = get_daemon_status()

    assert result["status"] == "running"
    assert pid_file.read_text(encoding="utf-8") == "7777"
