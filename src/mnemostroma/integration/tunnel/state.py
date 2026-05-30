# SPDX-License-Identifier: FSL-1.1-MIT
# tunnel/state.py — единственный читатель URL и token для всего UI слоя.
# Latency: <1ms (disk read).

from __future__ import annotations
import os
import sys
import json
import time
import logging
from enum import Enum
from pathlib import Path
from typing import NamedTuple, Any

logger = logging.getLogger("mnemostroma.tunnel.state")

try:
    import psutil
    _PSUTIL = True
except ImportError:
    _PSUTIL = False


def _get_base() -> Path:
    if sys.platform == "win32":
        # USERPROFILE надежнее HOME в Task Scheduler окружении
        base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        return Path(base) / ".mnemostroma"
    return Path.home() / ".mnemostroma"


_BASE = _get_base()
_URL_FILE = _BASE / "tunnel_url"
_PID_FILE = _BASE / "serveo_tunnel.pid"  # Используем наш PID файл


class TunnelState(str, Enum):
    ACTIVE  = "active"    # PID жив + URL получен
    STALE   = "stale"     # PID жив, URL еще нет (запускается или завис)
    DEAD    = "dead"      # нет ни PID, ни URL


class TunnelSnapshot(NamedTuple):
    state:  TunnelState
    url:    str | None
    pid:    int | None


def read_snapshot() -> TunnelSnapshot:
    """
    Читает состояние туннеля из файловой системы.
    Не требует IPC, работает из любого процесса (трей, расширение, watchdog).
    Атомарен: файлы пишутся через tmp→rename.
    """
    pid: int | None = None
    pid_alive = False

    if _PID_FILE.exists():
        try:
            pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
            if _PSUTIL:
                pid_alive = psutil.pid_exists(pid)
            else:
                # Fallback без psutil: os.kill(pid, 0) — работает Linux/macOS/Win
                try:
                    os.kill(pid, 0)
                    pid_alive = True
                except (OSError, ProcessLookupError):
                    pid_alive = False
        except Exception:
            pid = None

    url: str | None = None
    if _URL_FILE.exists():
        try:
            raw = _URL_FILE.read_text(encoding="utf-8").strip()
            if raw:
                url = raw
        except Exception:
            pass

    if pid_alive and url:
        return TunnelSnapshot(TunnelState.ACTIVE, url, pid)
    if pid_alive:
        return TunnelSnapshot(TunnelState.STALE, None, pid)

    # Очистка устаревших файлов состояния
    if not pid_alive and (_PID_FILE.exists() or _URL_FILE.exists()):
        _cleanup_stale_files()

    return TunnelSnapshot(TunnelState.DEAD, None, None)


def _cleanup_stale_files() -> None:
    for f in (_PID_FILE, _URL_FILE):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def force_kill_tunnel() -> bool:
    """
    Уничтожает cloudflared/ssh по PID-файлу.
    Работает вне зависимости от состояния TunnelManager в памяти.
    Используется кнопкой Force Kill в трее.
    Возвращает True если процесс был убит, False если PID не найден.
    """
    snap = read_snapshot()
    if snap.pid is None:
        _cleanup_stale_files()
        return False
    try:
        if _PSUTIL:
            proc = psutil.Process(snap.pid)
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except psutil.TimeoutExpired:
                proc.kill()
        else:
            import signal
            if sys.platform == "win32":
                import subprocess
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(snap.pid)],
                    capture_output=True
                )
            else:
                os.kill(snap.pid, signal.SIGTERM)
                time.sleep(2)
                try:
                    os.kill(snap.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
    except Exception as e:
        logger.warning("force_kill_tunnel error: %s", e)
    finally:
        _cleanup_stale_files()
    return True


def get_tunnel_url() -> str | None:
    """
    Читает URL активного туннеля из flat-файла (для обратной совместимости).
    """
    return read_snapshot().url


def get_tunnel_token() -> str | None:
    """
    Читает Bearer token туннеля через официальный API.
    """
    try:
        from mnemostroma.integration.tunnel.token import get_tunnel_token as _get
        return _get()
    except Exception as e:
        logger.warning("tunnel_token read error: %s", e)
        return None
