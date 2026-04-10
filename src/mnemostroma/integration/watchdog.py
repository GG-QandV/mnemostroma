# SPDX-License-Identifier: FSL-1.1-MIT
"""Watchdog — детектирует crash и hang daemon и proxy.

Запускается systemd отдельно от daemon и proxy.
Проверяет каждые CHECK_INTERVAL секунд.
Recovery < 5 секунд при любом сценарии:
  CHECK_INTERVAL=1 + HEARTBEAT_TIMEOUT=3 + RestartSec=1 = 5s worst case.
"""
import asyncio
import json
import logging
import os
import signal
import time
from pathlib import Path

import httpx

logger = logging.getLogger("mnemostroma.watchdog")

_MNEMO_DIR      = Path.home() / ".mnemostroma"
_HEARTBEAT_FILE = _MNEMO_DIR / "daemon.heartbeat"
_SOCKET_PATH    = _MNEMO_DIR / "daemon.sock"
_PID_DAEMON     = _MNEMO_DIR / "daemon.pid"
_PID_PROXY      = _MNEMO_DIR / "proxy.pid"

HEARTBEAT_TIMEOUT = 3    # секунд без обновления = hang
PROXY_TIMEOUT     = 3    # секунд на /health
CHECK_INTERVAL    = 1    # секунд между проверками

# sd_notify — опционально, для systemd WatchdogSec
try:
    import sdnotify as _sdn
    _sd = _sdn.SystemdNotifier()
    _SD = True
except ImportError:
    _SD = False


def _notify_systemd() -> None:
    if _SD:
        _sd.notify("WATCHDOG=1")


def _heartbeat_ok() -> bool:
    try:
        ts = int(_HEARTBEAT_FILE.read_text().strip())
        return (time.time() - ts) < HEARTBEAT_TIMEOUT
    except Exception:
        return False


async def _socket_responsive() -> bool:
    """Проверяет что socket принимает запросы — не просто существует."""
    if not _SOCKET_PATH.exists():
        return False
    try:
        r, w = await asyncio.wait_for(
            asyncio.open_unix_connection(str(_SOCKET_PATH)),
            timeout=2.0,
        )
        w.write(
            (json.dumps({"id": 1, "tool": "ctx_active", "args": {}}) + "\n").encode()
        )
        await w.drain()
        line = await asyncio.wait_for(r.readline(), timeout=2.0)
        w.close()
        return len(line) > 0
    except Exception:
        return False


async def _proxy_healthy() -> bool:
    try:
        async with httpx.AsyncClient(timeout=PROXY_TIMEOUT) as c:
            r = await c.get("http://127.0.0.1:8767/health")
            return r.status_code == 200
    except Exception:
        return False


def _kill(pid_file: Path, sig: signal.Signals = signal.SIGKILL) -> None:
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, sig)
        logger.warning(f"Sent {sig.name} to PID {pid} ({pid_file.name})")
    except (FileNotFoundError, ProcessLookupError, ValueError):
        pass


def _clean_socket() -> None:
    _SOCKET_PATH.unlink(missing_ok=True)
    logger.info("Removed stale socket")


async def _check_daemon() -> None:
    hb_ok     = _heartbeat_ok()
    sock_ok   = await _socket_responsive()

    if hb_ok and sock_ok:
        return  # норма

    if _HEARTBEAT_FILE.exists() and not hb_ok:
        logger.error("Daemon HANG (heartbeat stale) → SIGKILL")
        _kill(_PID_DAEMON, signal.SIGKILL)
        _clean_socket()
        # systemd Restart=always поднимет daemon снова
        return

    if _SOCKET_PATH.exists() and not sock_ok:
        logger.error("Socket stale (no response) → clean + SIGTERM")
        _clean_socket()
        _kill(_PID_DAEMON, signal.SIGTERM)


async def _check_proxy() -> None:
    if not await _proxy_healthy():
        logger.warning("Proxy DOWN or HANG → SIGKILL")
        _kill(_PID_PROXY, signal.SIGKILL)


async def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s watchdog %(levelname)s %(message)s",
    )
    logger.info(
        f"Watchdog started: check every {CHECK_INTERVAL}s, "
        f"hang threshold {HEARTBEAT_TIMEOUT}s"
    )
    while True:
        await asyncio.gather(_check_daemon(), _check_proxy())
        _notify_systemd()
        await asyncio.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    asyncio.run(run())
