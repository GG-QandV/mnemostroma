import pytest
from unittest.mock import patch, MagicMock
import psutil
from mnemostroma.cli import _is_process_alive, _ensure_pid_file, _remove_pid_safe

# T-01: PermissionError → процесс живой, PID-файл НЕ удалён
def test_permission_error_keeps_pid_file(tmp_path):
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("9999", encoding="utf-8")
    
    with patch("psutil.Process") as mock:
        mock.return_value.status.side_effect = psutil.AccessDenied(9999)
        result = _is_process_alive(9999)
    
    assert result is True          # процесс считается живым
    assert pid_file.exists()       # файл НЕ удалён

# T-02: NoSuchProcess → процесс мёртв, PID-файл удаляется
def test_no_such_process_removes_pid_file(tmp_path):
    with patch("psutil.pid_exists", return_value=False):
        assert _is_process_alive(9999) is False

# T-03: Zombie-процесс → считается мёртвым
def test_zombie_process_returns_false():
    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process") as mock:
        mock.return_value.status.return_value = psutil.STATUS_ZOMBIE
        assert _is_process_alive(9999) is False

# T-04: Нормальный живой процесс → True
def test_alive_process_returns_true():
    with patch("psutil.pid_exists", return_value=True), \
         patch("psutil.Process") as mock:
        mock.return_value.status.return_value = psutil.STATUS_RUNNING
        assert _is_process_alive(9999) is True

# T-05: pid=None → False без исключений
def test_none_pid_returns_false():
    assert _is_process_alive(None) is False

# T-06: PID-файл отсутствует, процесс найден → файл восстановлен
def test_pid_file_restored_when_missing(tmp_path):
    mock_proc = MagicMock()
    mock_proc.pid = 1234
    mock_proc.info = {"cmdline": ["python", "-m", "mnemostroma", "conductor"]}
    with patch("psutil.process_iter", return_value=[mock_proc]):
        _ensure_pid_file(tmp_path)
    assert (tmp_path / "daemon.pid").read_text() == "1234"

# T-07: PID-файл отсутствует, процесс НЕ найден → файл не создаётся
def test_pid_file_not_created_if_no_process(tmp_path):
    with patch("psutil.process_iter", return_value=[]):
        _ensure_pid_file(tmp_path)
    assert not (tmp_path / "daemon.pid").exists()

# T-08: AccessDenied при итерации процессов → не падает, продолжает поиск
def test_pid_restore_survives_access_denied(tmp_path):
    bad_proc = MagicMock()
    bad_proc.info = {"cmdline": None}
    bad_proc.__iter__ = MagicMock(side_effect=psutil.AccessDenied(0))
    # не должно бросить исключение
    _ensure_pid_file(tmp_path)
