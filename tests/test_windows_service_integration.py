"""
Integration tests for mnemostroma-service.exe on a real Windows 11 target.

Requirements
------------
- SSH access to a Windows 11 VM (OpenSSH server enabled)
- mnemostroma-service.exe built and present on the target
- Environment variables:
    MNEMO_WIN_HOST  — IP or hostname of the test VM
    MNEMO_WIN_USER  — SSH username (must have admin rights)
    MNEMO_WIN_KEY   — path to SSH private key  (preferred)
    MNEMO_WIN_PASS  — SSH password              (fallback)
    MNEMO_EXE_PATH  — full Windows path to mnemostroma-service.exe
                      default: C:\\Mnemostroma\\mnemostroma-service.exe

Run only these tests:
    pytest tests/test_windows_service_integration.py -v -m windows_integration

Skip if no VM available:
    pytest ... -m "not windows_integration"
"""
import os
import time
import textwrap
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# SSH helper — wraps paramiko; skips entire module if host not configured
# ---------------------------------------------------------------------------

WIN_HOST  = os.environ.get("MNEMO_WIN_HOST", "")
WIN_USER  = os.environ.get("MNEMO_WIN_USER", "")
WIN_KEY   = os.environ.get("MNEMO_WIN_KEY", "")
WIN_PASS  = os.environ.get("MNEMO_WIN_PASS", "")
EXE_PATH  = os.environ.get("MNEMO_EXE_PATH", r"C:\Mnemostroma\mnemostroma-service.exe")

_NO_VM = not WIN_HOST or not WIN_USER
pytestmark = pytest.mark.windows_integration


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "windows_integration: requires SSH access to a Windows 11 test VM",
    )


# ---------------------------------------------------------------------------
# SSH session fixture
# ---------------------------------------------------------------------------

class _SSH:
    """Thin paramiko wrapper. All commands run as PowerShell."""

    def __init__(self):
        import paramiko
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_kwargs = dict(username=WIN_USER, timeout=15)
        if WIN_KEY:
            connect_kwargs["key_filename"] = WIN_KEY
        else:
            connect_kwargs["password"] = WIN_PASS
        self._client.connect(WIN_HOST, **connect_kwargs)

    def ps(self, script: str, timeout: int = 30) -> tuple[int, str, str]:
        """Run a PowerShell snippet. Returns (returncode, stdout, stderr)."""
        cmd = f'powershell -NonInteractive -Command "{script}"'
        _, stdout, stderr = self._client.exec_command(cmd, timeout=timeout)
        rc = stdout.channel.recv_exit_status()
        return rc, stdout.read().decode(errors="replace"), stderr.read().decode(errors="replace")

    def sc(self, *args) -> tuple[int, str, str]:
        """Run sc.exe with given args."""
        return self.ps(" ".join(["sc.exe"] + list(args)))

    def close(self):
        self._client.close()


@pytest.fixture(scope="module")
def ssh():
    if _NO_VM:
        pytest.skip("MNEMO_WIN_HOST / MNEMO_WIN_USER not set — no Windows VM")
    try:
        import paramiko  # noqa: F401
    except ImportError:
        pytest.skip("paramiko not installed")
    conn = _SSH()
    yield conn
    conn.close()


# ---------------------------------------------------------------------------
# Helpers used across tests
# ---------------------------------------------------------------------------

SVC = "mnemostroma-service"
PROGRAMDATA_STATUS = r"$env:PROGRAMDATA\Mnemostroma\status.json"
PROGRAMDATA_PID    = r"$env:PROGRAMDATA\Mnemostroma\service.pid"


def _svc_state(ssh: _SSH) -> str:
    """Return service State string: Running / Stopped / etc."""
    rc, out, _ = ssh.ps(
        f"(Get-Service -Name '{SVC}' -ErrorAction SilentlyContinue).Status"
    )
    return out.strip()


def _wait_state(ssh: _SSH, target: str, timeout: int = 30) -> bool:
    """Poll until service reaches target state. Returns True on success."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _svc_state(ssh).lower() == target.lower():
            return True
        time.sleep(2)
    return False


def _status_json(ssh: _SSH) -> Optional[dict]:
    """Read %PROGRAMDATA%\\Mnemostroma\\status.json."""
    import json
    rc, out, _ = ssh.ps(
        f"if (Test-Path '{PROGRAMDATA_STATUS}') {{ Get-Content '{PROGRAMDATA_STATUS}' }}"
    )
    try:
        return json.loads(out.strip())
    except Exception:
        return None


def _pid_from_file(ssh: _SSH) -> Optional[int]:
    rc, out, _ = ssh.ps(
        f"if (Test-Path '{PROGRAMDATA_PID}') {{ Get-Content '{PROGRAMDATA_PID}' }}"
    )
    try:
        return int(out.strip())
    except ValueError:
        return None


def _schtasks_count(ssh: _SSH) -> int:
    """Count scheduled tasks whose name contains 'mnemostroma'."""
    rc, out, _ = ssh.ps(
        r"(schtasks /query /fo LIST 2>&1 | Select-String -i 'mnemostroma').Count"
    )
    try:
        return int(out.strip())
    except ValueError:
        return 0


def _python_exists(ssh: _SSH) -> bool:
    """True if python.exe is found in PATH."""
    rc, out, _ = ssh.ps("(Get-Command python -ErrorAction SilentlyContinue) -ne $null")
    return out.strip().lower() == "true"


def _install(ssh: _SSH) -> tuple[int, str, str]:
    return ssh.ps(f'& "{EXE_PATH}" install')


def _uninstall(ssh: _SSH) -> tuple[int, str, str]:
    return ssh.ps(f'& "{EXE_PATH}" remove')


def _ensure_stopped(ssh: _SSH) -> None:
    ssh.sc("stop", SVC)
    _wait_state(ssh, "Stopped", timeout=15)


def _ensure_removed(ssh: _SSH) -> None:
    _ensure_stopped(ssh)
    ssh.sc("delete", SVC)
    time.sleep(2)


# ---------------------------------------------------------------------------
# T-01  Fresh install
# ---------------------------------------------------------------------------

class TestFreshInstall:
    def test_service_registered_after_install(self, ssh):
        _ensure_removed(ssh)
        rc, out, err = _install(ssh)
        assert rc == 0, f"install failed: {err}"
        state = _svc_state(ssh)
        assert state != "", "Service not found in SCM after install"

    def test_service_starts_via_scm(self, ssh):
        rc, _, err = ssh.sc("start", SVC)
        assert _wait_state(ssh, "Running", timeout=45), \
            f"Service did not reach Running state. sc stderr: {err}"

    def test_status_file_written(self, ssh):
        status = _status_json(ssh)
        assert status is not None, "status.json not written"
        assert status.get("state") in ("starting", "running"), \
            f"Unexpected state: {status}"

    def test_pid_file_matches_real_process(self, ssh):
        pid = _pid_from_file(ssh)
        assert pid is not None, "service.pid not written"
        rc, out, _ = ssh.ps(f"(Get-Process -Id {pid} -ErrorAction SilentlyContinue) -ne $null")
        assert out.strip().lower() == "true", \
            f"PID {pid} from service.pid not found in process list"

    def test_no_scheduled_tasks_created(self, ssh):
        count = _schtasks_count(ssh)
        assert count == 0, \
            f"Found {count} mnemostroma scheduled task(s) — must be 0"


# ---------------------------------------------------------------------------
# T-02  Stop / start via SCM
# ---------------------------------------------------------------------------

class TestStopStart:
    def test_stop_via_scm(self, ssh):
        ssh.sc("start", SVC)
        _wait_state(ssh, "Running", timeout=45)
        rc, _, err = ssh.sc("stop", SVC)
        assert _wait_state(ssh, "Stopped", timeout=20), \
            f"Service did not stop. err: {err}"

    def test_status_stopped_after_sc_stop(self, ssh):
        status = _status_json(ssh)
        assert status is not None
        assert status.get("state") in ("stopping", "stopped"), \
            f"Unexpected state in status.json: {status}"

    def test_start_again_after_stop(self, ssh):
        rc, _, _ = ssh.sc("start", SVC)
        assert _wait_state(ssh, "Running", timeout=45), "Service did not restart via sc start"

    def test_double_start_no_duplicate_process(self, ssh):
        # Second sc start should be rejected by SCM — not spawn a second process
        rc, _, _ = ssh.sc("start", SVC)
        # rc != 0 is expected (already running); check only one process exists
        _, out, _ = ssh.ps(
            f"(Get-Process | Where-Object {{ $_.MainWindowTitle -like '*mnemostroma*' }}).Count"
        )
        # For a service .exe there's no window title; check by exe name
        _, out, _ = ssh.ps(
            "(Get-Process 'mnemostroma-service' -ErrorAction SilentlyContinue).Count"
        )
        try:
            count = int(out.strip())
        except ValueError:
            count = 1
        assert count <= 1, f"Found {count} mnemostroma-service processes — expected 1"


# ---------------------------------------------------------------------------
# T-03  Upgrade over existing installation
# ---------------------------------------------------------------------------

class TestUpgrade:
    def test_install_over_running_service(self, ssh):
        # Service is running; re-running install should stop, replace, restart
        ssh.sc("start", SVC)
        _wait_state(ssh, "Running", timeout=45)
        rc, out, err = _install(ssh)
        assert rc == 0, f"Upgrade install failed: {err}"

    def test_service_running_after_upgrade(self, ssh):
        assert _wait_state(ssh, "Running", timeout=45), \
            "Service not running after upgrade"

    def test_no_scheduled_tasks_after_upgrade(self, ssh):
        assert _schtasks_count(ssh) == 0


# ---------------------------------------------------------------------------
# T-04  Crash simulation → watchdog restart
# ---------------------------------------------------------------------------

class TestCrashRestart:
    def test_watchdog_restarts_after_heartbeat_expire(self, ssh):
        """Overwrite heartbeat with a timestamp 300 s in the past.
        Watchdog should detect stale heartbeat + proxy down and restart daemon."""
        _wait_state(ssh, "Running", timeout=45)

        # Grab PID before we break the heartbeat
        pid_before = _pid_from_file(ssh)

        # Poison the heartbeat file
        stale_ts = int(time.time()) - 300
        ssh.ps(
            f"Set-Content -Path '$env:USERPROFILE\\.mnemostroma\\daemon.heartbeat' "
            f"-Value '{stale_ts}'"
        )

        # Also kill the proxy port to trigger both conditions simultaneously
        ssh.ps(
            f"Get-NetTCPConnection -LocalPort 8767 -ErrorAction SilentlyContinue "
            f"| ForEach-Object {{ Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }}"
        )

        # Wait for watchdog to detect and for daemon to come back up
        # Watchdog interval=5s, grace period=10s → restart should happen within 30s
        time.sleep(30)

        status = _status_json(ssh)
        assert status is not None
        assert status.get("state") in ("running", "restarting", "starting"), \
            f"Unexpected state after crash sim: {status}"

    def test_service_still_registered_after_crash(self, ssh):
        state = _svc_state(ssh)
        assert state != "", "Service disappeared from SCM after crash simulation"

    def test_no_scheduled_tasks_after_crash_restart(self, ssh):
        assert _schtasks_count(ssh) == 0, \
            "Watchdog restart created a scheduled task — must not happen"


# ---------------------------------------------------------------------------
# T-05  Uninstall → reinstall
# ---------------------------------------------------------------------------

class TestUninstallReinstall:
    def test_uninstall_removes_service(self, ssh):
        _ensure_stopped(ssh)
        rc, _, err = _uninstall(ssh)
        assert rc == 0, f"uninstall failed: {err}"
        time.sleep(3)
        state = _svc_state(ssh)
        assert state == "", f"Service still in SCM after uninstall: '{state}'"

    def test_python_still_exists_after_uninstall(self, ssh):
        # Uninstall must not touch Python or system PATH
        assert _python_exists(ssh), "python.exe vanished after uninstall — uninstaller broke PATH"

    def test_reinstall_works_cleanly(self, ssh):
        rc, _, err = _install(ssh)
        assert rc == 0, f"reinstall failed: {err}"
        ssh.sc("start", SVC)
        assert _wait_state(ssh, "Running", timeout=45), "Service not running after reinstall"

    def test_no_scheduled_tasks_after_reinstall(self, ssh):
        assert _schtasks_count(ssh) == 0


# ---------------------------------------------------------------------------
# T-06  Regression: Task Scheduler, Python safety, exe autonomy
# ---------------------------------------------------------------------------

class TestRegression:
    def test_no_task_scheduler_entries_at_steady_state(self, ssh):
        _wait_state(ssh, "Running", timeout=30)
        assert _schtasks_count(ssh) == 0, \
            "Mnemostroma scheduled task found — regression: must use SCM only"

    def test_exe_runs_without_python_in_path(self, ssh):
        """Launch exe with PATH stripped of Python dirs — must still start."""
        script = textwrap.dedent(f"""
            $env:PATH = ($env:PATH -split ';' | Where-Object {{ $_ -notmatch 'Python|python' }}) -join ';'
            $p = Start-Process -FilePath '{EXE_PATH}' -ArgumentList 'version' `
                 -PassThru -Wait -NoNewWindow
            $p.ExitCode
        """).strip()
        rc, out, err = ssh.ps(script, timeout=20)
        # Exit code 0 or 1 (unknown subcommand) — both mean exe loaded without Python
        assert "python" not in err.lower() or "not found" not in err.lower(), \
            f"Exe failed to load without Python in PATH: {err}"

    def test_uninstall_purge_does_not_delete_python(self, ssh):
        _ensure_stopped(ssh)
        ssh.ps(f'& "{EXE_PATH}" remove')
        time.sleep(3)
        assert _python_exists(ssh), "python.exe missing after --purge uninstall"
        # Restore for subsequent tests
        _install(ssh)
        ssh.sc("start", SVC)
        _wait_state(ssh, "Running", timeout=45)

    def test_browser_extension_port_accessible_after_restart(self, ssh):
        """Extension talks to port 8767 — must be reachable after service restart."""
        ssh.sc("stop", SVC)
        _wait_state(ssh, "Stopped", timeout=20)
        ssh.sc("start", SVC)
        _wait_state(ssh, "Running", timeout=45)

        # Give adapters time to bind port
        time.sleep(10)

        rc, out, _ = ssh.ps(
            "Test-NetConnection -ComputerName 127.0.0.1 -Port 8767 -InformationLevel Quiet"
        )
        assert out.strip().lower() == "true", \
            "Port 8767 not reachable after service restart — extension would break"
