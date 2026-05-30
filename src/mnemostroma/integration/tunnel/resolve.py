# SPDX-License-Identifier: FSL-1.1-MIT
import os
import sys
import shutil
from pathlib import Path

def resolve_mnemostroma_executable() -> list[str]:
    """
    Возвращает аргументы для subprocess, гарантированно работающие
    в headless/non-login окружении (systemd, Task Scheduler, IDE).
    Приоритет: sys.executable -m mnemostroma.
    """
    return [sys.executable, "-m", "mnemostroma"]

def resolve_cloudflared_executable() -> str:
    """
    Возвращает абсолютный путь к cloudflared.
    ~/.mnemostroma/bin/cloudflared имеет приоритет над системным.
    """
    local = Path.home() / ".mnemostroma" / "bin" / (
        "cloudflared.exe" if sys.platform == "win32" else "cloudflared"
    )
    if local.exists():
        return str(local)
    system = shutil.which("cloudflared")
    if system:
        return system
    raise FileNotFoundError(
        "cloudflared не найден. Запустите: mnemostroma tunnel start "
        "(автоматически скачает cloudflared в ~/.mnemostroma/bin)"
    )

def _is_headless() -> bool:
    """True если запуск из неинтерактивной оболочки (трей, Task Scheduler, IDE)."""
    if not sys.stdin or not sys.stdin.isatty():
        return True
    if sys.platform == "win32":
        # В Task Scheduler SESSIONNAME="" или отсутствует
        return os.environ.get("SESSIONNAME", "") == ""
    return os.environ.get("DISPLAY", "") == ""
