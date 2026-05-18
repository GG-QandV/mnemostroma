# SPDX-License-Identifier: FSL-1.1-MIT
"""
Windows SCM service wrapper for Mnemostroma.

Register:  mnemostroma-service.exe install
Controls:  sc start / stop / restart mnemostroma-service
Debug:     mnemostroma-service.exe debug   (runs in foreground, Ctrl+C to stop)

Internals:
  - Daemon + adapters run in-process on ProactorEventLoop
  - Internal watchdog checks every 5 s (heartbeat + proxy port)
  - Restart on failure with exponential backoff, up to 5 attempts
  - pid / status written to %PROGRAMDATA%\\Mnemostroma\\
"""
import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import servicemanager
import win32event
import win32service
import win32serviceutil

from mnemostroma.core.bootstrap import bootstrap

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Mnemostroma"
_MNEMO_DIR   = Path.home() / ".mnemostroma"
_PID_FILE    = _PROGRAMDATA / "service.pid"
_STATUS_FILE = _PROGRAMDATA / "status.json"
_LOG_FILE    = _PROGRAMDATA / "logs" / "service.log"
_CONFIG_PATH = _MNEMO_DIR / "config.json"
_DB_PATH     = _MNEMO_DIR / "mnemostroma.db"
_HEARTBEAT   = _MNEMO_DIR / "daemon.heartbeat"

# PyInstaller onefile: _MEIPASS is the temp extraction dir; models are inside it
if getattr(sys, "frozen", False):
    _MODEL_DIR = Path(sys._MEIPASS) / "models"
else:
    _MODEL_DIR = Path(__file__).resolve().parents[3] / "models"

# ---------------------------------------------------------------------------
# Watchdog tuning
# ---------------------------------------------------------------------------
_WD_INTERVAL_SEC     = 5    # how often watchdog checks daemon health
_HB_TIMEOUT_SEC      = 120  # heartbeat file age that triggers a restart
_PROXY_PORT          = 8767
_PROXY_TIMEOUT_SEC   = 3
_MAX_RESTARTS        = 5    # consecutive failures before service gives up
_BACKOFF_BASE_SEC    = 10   # first wait; doubles each failure, capped at 120 s

# ---------------------------------------------------------------------------
# Logging — file + stdout (stdout visible in SCM debug mode)
# ---------------------------------------------------------------------------

def _setup_logging() -> None:
    _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(str(_LOG_FILE), encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

logger = logging.getLogger("mnemostroma.service")

# ---------------------------------------------------------------------------
# pid / status helpers
# ---------------------------------------------------------------------------

def _write_pid() -> None:
    _PROGRAMDATA.mkdir(parents=True, exist_ok=True)
    _PID_FILE.write_text(str(os.getpid()))


def _write_status(state: str, **extra) -> None:
    payload = {"state": state, "pid": os.getpid(), "ts": time.time()}
    payload.update(extra)
    try:
        _STATUS_FILE.write_text(json.dumps(payload))
    except OSError:
        pass  # non-fatal — status file is informational only


# ---------------------------------------------------------------------------
# Watchdog probes (Windows-safe: no SIGKILL, no unix sockets, no pgrep)
# ---------------------------------------------------------------------------

def _heartbeat_ok() -> bool:
    try:
        ts = int(_HEARTBEAT.read_text().strip())
        return (time.time() - ts) < _HB_TIMEOUT_SEC
    except Exception:
        return False


async def _proxy_ok() -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", _PROXY_PORT),
            timeout=_PROXY_TIMEOUT_SEC,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Daemon runner — owns the asyncio event loop
# ---------------------------------------------------------------------------

class _DaemonRunner:
    """Runs Conductor in-process; watchdog restarts it on crash or hang."""

    def __init__(self, stop_event: threading.Event) -> None:
        self._stop = stop_event
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    # Called from a dedicated thread; blocks until service stops.
    def run(self) -> None:
        # ProactorEventLoop is required on Windows for subprocess + network I/O
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._supervisor())
        finally:
            self._loop.close()

    def request_stop(self) -> None:
        """Thread-safe: ask the event loop to exit."""
        if self._loop and not self._loop.is_closed():
            self._loop.call_soon_threadsafe(self._stop.set)

    async def _supervisor(self) -> None:
        failures = 0

        while not self._stop.is_set():
            if failures >= _MAX_RESTARTS:
                logger.error(
                    f"Daemon failed {failures} times in a row — service giving up. "
                    "Check %PROGRAMDATA%\\Mnemostroma\\logs\\service.log"
                )
                _write_status("failed", failures=failures)
                return

            logger.info(f"Starting daemon (attempt {failures + 1})")
            _write_status("starting", attempt=failures + 1)

            started_at = time.monotonic()
            try:
                conductor = await bootstrap(
                    config_path=_CONFIG_PATH,
                    db_path=_DB_PATH,
                    model_dir=_MODEL_DIR,
                )
            except Exception as exc:
                logger.exception(f"bootstrap() failed: {exc}")
                _write_status("bootstrap_failed", error=str(exc))
                failures += 1
                await self._backoff(failures)
                continue

            _write_status("running")
            logger.info("Daemon up — watchdog active")

            # Inner watchdog loop
            restart_requested = await self._watchdog_loop(conductor)

            uptime = time.monotonic() - started_at
            if uptime > _BACKOFF_BASE_SEC * 2:
                # Ran long enough — reset failure counter
                failures = 0
            else:
                failures += 1

            # Teardown before restart (or final stop)
            try:
                await asyncio.wait_for(conductor.stop(), timeout=10)
            except (asyncio.TimeoutError, Exception) as exc:
                logger.warning(f"conductor.stop() issue: {exc}")

            if not restart_requested:
                # Clean stop requested — exit supervisor
                _write_status("stopped")
                return

            logger.info(f"Daemon exited (uptime={uptime:.0f}s, failures={failures})")
            _write_status("restarting", failures=failures)
            if failures > 0:
                await self._backoff(failures)

        _write_status("stopped")

    async def _watchdog_loop(self, conductor) -> bool:
        """Monitor daemon health. Returns True if restart needed, False on clean stop."""
        # Grace period: give daemon time to write first heartbeat
        await asyncio.sleep(_WD_INTERVAL_SEC * 2)

        while not self._stop.is_set():
            await asyncio.sleep(_WD_INTERVAL_SEC)

            if self._stop.is_set():
                return False  # clean stop

            hb  = _heartbeat_ok()
            prx = await _proxy_ok()

            if not hb and not prx:
                logger.error("Watchdog: heartbeat expired + proxy down → restart")
                return True

            if not hb:
                logger.warning(f"Watchdog: heartbeat stale (proxy OK)")
            if not prx:
                logger.warning(f"Watchdog: proxy unreachable (heartbeat OK)")

        return False  # stop_event was set

    async def _backoff(self, failures: int) -> None:
        wait = min(_BACKOFF_BASE_SEC * (2 ** (failures - 1)), 120)
        logger.info(f"Waiting {wait}s before restart…")
        # Respect stop_event during backoff sleep
        for _ in range(int(wait)):
            if self._stop.is_set():
                return
            await asyncio.sleep(1)


# ---------------------------------------------------------------------------
# Windows SCM service class
# ---------------------------------------------------------------------------

class MnemostramaService(win32serviceutil.ServiceFramework):
    _svc_name_         = "mnemostroma-service"
    _svc_display_name_ = "Mnemostroma Service"
    _svc_description_  = (
        "Mnemostroma cognitive memory daemon. "
        "Runs MCP adapters and internal watchdog. "
        "IDE extensions (Claude, Cursor, etc.) depend on this service."
    )

    def __init__(self, args):
        super().__init__(args)
        self._scm_event  = win32event.CreateEvent(None, 0, 0, None)
        self._stop_event = threading.Event()
        self._runner: Optional[_DaemonRunner] = None
        self._thread:  Optional[threading.Thread] = None

    def SvcDoRun(self) -> None:
        _setup_logging()
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STARTED,
            (self._svc_name_, ""),
        )
        logger.info(f"Service starting — PID {os.getpid()}")
        _write_pid()
        _write_status("starting")

        self._runner = _DaemonRunner(self._stop_event)
        self._thread = threading.Thread(
            target=self._runner.run,
            daemon=True,
            name="mnemo-daemon",
        )
        self._thread.start()

        # Block here; SCM waits until SvcDoRun returns
        win32event.WaitForSingleObject(self._scm_event, win32event.INFINITE)

        self._thread.join(timeout=30)
        if self._thread.is_alive():
            logger.warning("Daemon thread did not exit within 30 s")

        logger.info("Service stopped")
        servicemanager.LogMsg(
            servicemanager.EVENTLOG_INFORMATION_TYPE,
            servicemanager.PYS_SERVICE_STOPPED,
            (self._svc_name_, ""),
        )

    def SvcStop(self) -> None:
        logger.info("Stop requested by SCM")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self._stop_event.set()
        if self._runner:
            self._runner.request_stop()
        win32event.SetEvent(self._scm_event)


# ---------------------------------------------------------------------------
# Entry point — handles both SCM dispatch and CLI install/remove/debug
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No args: SCM launched us — enter dispatcher
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(MnemostramaService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        # CLI: install / remove / start / stop / restart / debug
        win32serviceutil.HandleCommandLine(MnemostramaService)
