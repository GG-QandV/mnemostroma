# SPDX-License-Identifier: FSL-1.1-MIT
"""Watchdog — detects crashes and hangs of the daemon and proxy.

Separated into 2 phases:
1. Boot Phase: Wait up to 100s for first heartbeat.
2. Active Phase: Check every 15s for stagnation (120s threshold).
"""
import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

from mnemostroma.config import Config

logger = logging.getLogger("mnemostroma.watchdog")

_MNEMO_DIR      = Path.home() / ".mnemostroma"
_HEARTBEAT_FILE = _MNEMO_DIR / "daemon.heartbeat"
_SOCKET_PATH    = _MNEMO_DIR / "daemon.sock"
_PID_DAEMON     = _MNEMO_DIR / "daemon.pid"
_PID_PROXY      = _MNEMO_DIR / "proxy.pid"
_CONFIG_PATH    = _MNEMO_DIR / "config.json"

# Default fallback values (will be overwritten by config.json)
HEARTBEAT_TIMEOUT = 120
PROXY_TIMEOUT     = 5
CHECK_INTERVAL    = 15
STARTUP_FAILSAFE  = 100

# sd_notify — optional, for systemd WatchdogSec
try:
    import sdnotify as _sdn
    _sd = _sdn.SystemdNotifier()
    _SD = True
except ImportError:
    _SD = False


def _notify_systemd() -> None:
    if _SD:
        _sd.notify("WATCHDOG=1")


def _heartbeat_ok(timeout: int) -> bool:
    try:
        ts = int(_HEARTBEAT_FILE.read_text().strip())
        return (time.time() - ts) < timeout
    except Exception:
        return False


async def _socket_responsive() -> bool:
    """Checks that the socket accepts connections."""
    if not _SOCKET_PATH.exists():
        return False
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_unix_connection(str(_SOCKET_PATH)),
            timeout=2.0,
        )
        w.close()
        await w.wait_closed()
        return True
    except Exception:
        return False


async def _proxy_healthy(timeout: int) -> bool:
    """TCP connect check — no httpx needed."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 8767),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


def _kill(pid_file: Path, sig: signal.Signals = signal.SIGKILL) -> None:
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, sig)
        logger.warning(f"Sent {sig.name} to PID {pid} ({pid_file.name})")
    except (FileNotFoundError, ProcessLookupError, ValueError):
        pass


def _kill_all_daemon_instances(known_pid: int | None = None) -> None:
    """Kill all 'mnemostroma run' processes except this watchdog.

    Catches orphan daemons that overwrote daemon.pid and became invisible
    to the normal _kill() mechanism.
    """
    import subprocess
    try:
        result = subprocess.run(
            ["pgrep", "-f", r"mnemostroma run"],
            capture_output=True, text=True
        )
        my_pid = os.getpid()
        for pid_str in result.stdout.strip().splitlines():
            try:
                pid = int(pid_str)
                if pid == my_pid or pid == known_pid:
                    continue
                os.kill(pid, signal.SIGKILL)
                logger.warning(f"Killed orphan daemon PID {pid}")
            except (ProcessLookupError, ValueError):
                pass
    except Exception as e:
        logger.error(f"_kill_all_daemon_instances failed: {e}")


def _clean_socket() -> None:
    _SOCKET_PATH.unlink(missing_ok=True)
    logger.info("Removed stale socket")


async def _check_daemon(hb_timeout: int) -> None:
    hb_ok = _heartbeat_ok(hb_timeout)
    if hb_ok:
        return  # Normal or hydrating

    if _HEARTBEAT_FILE.exists() and not hb_ok:
        logger.error(f"Daemon HANG (no heartbeat for {hb_timeout}s) → SIGKILL")
        _kill(_PID_DAEMON, signal.SIGKILL)
        _kill_all_daemon_instances()
        _clean_socket()
        return

    sock_ok = await _socket_responsive()
    if _SOCKET_PATH.exists() and not sock_ok:
        logger.error("Socket stale (no response) → clean + SIGTERM")
        _clean_socket()
        _kill(_PID_DAEMON, signal.SIGTERM)
        _kill_all_daemon_instances()


async def _check_proxy(timeout: int) -> None:
    if not await _proxy_healthy(timeout):
        logger.warning("Proxy DOWN or HANG → SIGKILL")
        _kill(_PID_PROXY, signal.SIGKILL)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s watchdog %(levelname)s %(message)s",
    )
    
    # Load Config
    cfg_path = _CONFIG_PATH if _CONFIG_PATH.exists() else Path("config.json")
    try:
        config = Config.load(cfg_path)
        hb_timeout = config.watchdog.heartbeat_timeout_sec
        check_int = config.watchdog.check_interval_sec
        startup_failsafe = config.watchdog.startup_failsafe_sec
    except Exception as e:
        logger.warning(f"Failed to load config, using defaults: {e}")
        hb_timeout = HEARTBEAT_TIMEOUT
        check_int = CHECK_INTERVAL
        startup_failsafe = STARTUP_FAILSAFE

    logger.info(
        f"Watchdog started: check every {check_int}s, "
        f"failsafe {startup_failsafe}s, "
        f"hang threshold {hb_timeout}s"
    )
    
    # PHASE 1: Booting / Hydration Immunity
    logger.info(f"PHASE 1: Waiting for daemon & proxy ready (max {startup_failsafe}s)...")
    start_boot = time.time()
    while (time.time() - start_boot) < startup_failsafe:
        d_ok = _heartbeat_ok(20) # Daemon heartbeat started
        p_ok = await _proxy_healthy(2) # Proxy health port open
        
        if d_ok and p_ok:
            logger.info("System healthy. Entering PHASE 2 (Active).")
            break
        await asyncio.sleep(5)
    else:
        logger.error(f"System failed to stabilize within {startup_failsafe}s → Emergency Exit")
        _kill(_PID_DAEMON, signal.SIGKILL)
        _kill(_PID_PROXY, signal.SIGKILL)
        return

    # PHASE 2: Active Monitoring
    while True:
        await asyncio.gather(
            _check_daemon(hb_timeout), 
            _check_proxy(PROXY_TIMEOUT)
        )
        _notify_systemd()
        await asyncio.sleep(check_int)


if __name__ == "__main__":
    asyncio.run(run())
