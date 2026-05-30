# SPDX-License-Identifier: FSL-1.1-MIT
# tunnel/state.py — единственный читатель URL и token для всего UI слоя.
# Latency: <1ms (disk read).

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path
from typing import NamedTuple

logger = logging.getLogger("mnemostroma.tunnel.state")


def _import_psutil() -> bool:
    global psutil, _PSUTIL
    try:
        import psutil
        _PSUTIL = True
    except ImportError:
        _PSUTIL = False
    return _PSUTIL


_PSUTIL = False
_import_psutil()


def _get_base() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("USERPROFILE") or os.path.expanduser("~")
        return Path(base) / ".mnemostroma"
    return Path.home() / ".mnemostroma"


_BASE = _get_base()
_URL_FILE = _BASE / "tunnel_url"
_PID_FILE = _BASE / "serveo_tunnel.pid"

_TUNNEL_PROCESS_NAMES: frozenset[str] = frozenset({
    "cloudflared",
    "cloudflared.exe",
    "ssh",       # serveo SSH tunnel
})


class TunnelState(str, Enum):
    ACTIVE  = "active"    # PID жив + URL получен
    STALE   = "stale"     # PID жив, URL ещё нет (запускается или завис)
    DEAD    = "dead"      # нет ни PID, ни URL


class TunnelSnapshot(NamedTuple):
    state:  TunnelState
    url:    str | None
    pid:    int | None


def _is_pid_alive(pid: int) -> bool:
    """Кросс-платформенная проверка PID. psutil предпочтительнее."""
    if _PSUTIL:
        return psutil.pid_exists(pid)
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
    except PermissionError:
        return True   # Win: процесс есть, нет прав на query


def read_snapshot() -> TunnelSnapshot:
    """
    Читает состояние туннеля из файловой системы.
    Правило: _cleanup_stale_files() вызывается ТОЛЬКО если PID-файл
    существует и PID мёртв. Если PID-файла нет — не трогаем URL.
    """
    pid: int | None = None
    pid_file_exists = _PID_FILE.exists()
    pid_alive = False

    if pid_file_exists:
        try:
            pid = int(_PID_FILE.read_text(encoding="utf-8").strip())
            pid_alive = _is_pid_alive(pid)
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

    # PID-файл есть, процесс мёртв — реальный stale, чистим
    if pid_file_exists and not pid_alive:
        _cleanup_stale_files()
        return TunnelSnapshot(TunnelState.DEAD, None, None)

    # PID-файла нет, но URL есть — туннель стартует, не трогаем
    if not pid_file_exists and url:
        return TunnelSnapshot(TunnelState.STALE, None, None)

    return TunnelSnapshot(TunnelState.DEAD, None, None)


def _cleanup_stale_files() -> None:
    for f in (_PID_FILE, _URL_FILE):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def force_kill_tunnel() -> bool:
    """Уничтожает процесс по PID-файлу. Возвращает True если был убит."""
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


# ─── Orphan hunt by process name ───────────────────────────────────────────────

def _is_tunnel_process(name: str, cmdline: str) -> bool:
    """Проверяет, является ли процесс туннельным/адаптерным."""
    name_lower = name.lower()
    if name_lower in _TUNNEL_PROCESS_NAMES:
        return True
    # Python модули
    if "mcp_oauth_adapter" in cmdline or "mcpoauthadapter" in cmdline:
        return True
    # cloudflared запущенный через mnemostroma
    if "cloudflared" in cmdline and ("mnemostroma" in cmdline or "tunnel" in cmdline):
        return True
    # tunnel manager foreground процесс
    if "tunnel" in cmdline and "start" in cmdline and "--foreground" in cmdline:
        return True
    return False


def kill_orphan_tunnel_processes() -> list[int]:
    """
    Убивает ВСЕ процессы cloudflared/ssh/mcp_oauth_adapter по имени,
    независимо от PID-файла. Требует psutil.
    Возвращает список убитых PID.
    """
    if not _import_psutil():
        logger.warning("psutil not available, skipping orphan hunt")
        return []

    killed: list[int] = []
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = " ".join(proc.info.get("cmdline") or []).lower()
            if _is_tunnel_process(name, cmdline):
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except psutil.TimeoutExpired:
                    proc.kill()
                killed.append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    # Windows fallback: taskkill по имени
    if sys.platform == "win32":
        for exe in ("cloudflared.exe",):
            try:
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe],
                    capture_output=True, timeout=5
                )
            except Exception:
                pass

    _cleanup_stale_files()
    return killed


# ─── Port occupant kill (освободить порт перед стартом) ──────────────────────

def _kill_via_lsof(port: int) -> list[int]:
    """macOS/Linux: lsof -ti :PORT | xargs kill."""
    killed: list[int] = []
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0 and result.stdout.strip():
            pids = [int(p) for p in result.stdout.strip().split()]
            for pid in pids:
                try:
                    os.kill(pid, 15)  # SIGTERM
                    killed.append(pid)
                except (OSError, ProcessLookupError):
                    pass
            time.sleep(1)
            for pid in pids:
                try:
                    os.kill(pid, 9)   # SIGKILL
                except (OSError, ProcessLookupError):
                    pass
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return killed


def _kill_via_fuser(port: int) -> list[int]:
    """Linux: fuser -k PORT/tcp."""
    killed: list[int] = []
    try:
        result = subprocess.run(
            ["fuser", "-k", f"{port}/tcp"],
            capture_output=True, timeout=5
        )
        if result.returncode == 0:
            killed.append(0)  # сигнал что убито
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        pass
    return killed


def _kill_via_netstat(port: int) -> list[int]:
    """Windows: netstat -ano | findstr :PORT → taskkill."""
    killed: list[int] = []
    try:
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5
        )
        for line in result.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.strip().split()
                if parts:
                    pid_str = parts[-1]
                    try:
                        pid = int(pid_str)
                        subprocess.run(
                            ["taskkill", "/F", "/PID", str(pid)],
                            capture_output=True, timeout=5
                        )
                        killed.append(pid)
                    except (ValueError, subprocess.TimeoutExpired):
                        pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return killed


def _kill_port_occupants(port: int) -> list[int]:
    """
    Убивает процессы, занимающие TCP-порт.
    Стратегия (по порядку):
      1. psutil.net_connections() — быстро, но может не быть прав
      2. os-specific fallback: lsof (macOS/Linux), fuser (Linux), netstat (Windows)
    Возвращает список убитых PID.
    """
    killed: list[int] = []

    # Попытка 1: psutil
    if _import_psutil():
        try:
            for conn in psutil.net_connections(kind="tcp"):
                if (conn.laddr and conn.laddr.port == port
                        and conn.status == "LISTEN"):
                    try:
                        proc = psutil.Process(conn.pid)
                        proc.terminate()
                        try:
                            proc.wait(timeout=2)
                        except psutil.TimeoutExpired:
                            proc.kill()
                        killed.append(conn.pid)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            if killed:
                return killed
        except (psutil.AccessDenied, PermissionError):
            logger.debug("psutil.net_connections() denied, trying fallback")

    # Попытка 2: платформо-зависимые утилиты
    if sys.platform == "win32":
        killed = _kill_via_netstat(port)
    elif sys.platform == "darwin":
        killed = _kill_via_lsof(port)
    else:
        # Linux — пробуем fuser, затем lsof
        killed = _kill_via_fuser(port)
        if not killed:
            killed = _kill_via_lsof(port)

    return killed


# ─── Public helpers ────────────────────────────────────────────────────────────

def get_tunnel_url() -> str | None:
    """Читает URL активного туннеля из flat-файла."""
    return read_snapshot().url


def get_tunnel_token() -> str | None:
    """Читает Bearer token туннеля."""
    try:
        from mnemostroma.integration.tunnel.token import get_tunnel_token as _get
        return _get()
    except Exception as e:
        logger.warning("tunnel_token read error: %s", e)
        return None
