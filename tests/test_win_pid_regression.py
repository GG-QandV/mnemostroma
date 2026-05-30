import pytest
from unittest.mock import patch, MagicMock
import psutil
from mnemostroma.cli import _is_process_alive, _print_status

# T-12: os.kill нигде не вызывается в _is_process_alive
def test_no_os_kill_in_process_check():
    import mnemostroma.cli.commands as cli_module
    import inspect
    source = inspect.getsource(cli_module._is_process_alive)
    assert "os.kill" not in source, "os.kill must not be used for process check"

# T-13: _remove_pid не вызывается при AccessDenied (regression guard)
def test_remove_pid_not_called_on_access_denied(tmp_path):
    pid_file = tmp_path / "daemon.pid"
    pid_file.write_text("9999", encoding="utf-8")

    with patch("psutil.Process") as mock, \
         patch("mnemostroma.cli.commands._remove_pid") as mock_remove:
        mock.return_value.status.side_effect = psutil.AccessDenied(9999)
        _print_status(pid_path=pid_file)

    mock_remove.assert_not_called()
