#!/usr/bin/env python3
# SPDX-License-Identifier: FSL-1.1-MIT
"""Serveo Manager: SSH-туннели через serveo.net для Mnemostroma MCP."""

import json
import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mnemostroma.serveo")

CONFIGS_DIR = Path(__file__).parent / "serveo_client_configs"
SERVEO_HOST = "serveo.net"
DEFAULT_MCP_PORT = 8768
_BACKOFF = [5, 15, 30, 60]  # reconnect delays in seconds

# ── F1: SSH preflight ──────────────────────────────────────────────────────

import sys

def check_ssh_available() -> Optional[str]:
    path = shutil.which("ssh")
    if path is None and sys.platform == "win32":
        raise RuntimeError(
            "OpenSSH Client не найден.\n"
            "Установите через: Settings → Apps → Optional Features → OpenSSH Client\n"
            "или выполните: winget install Microsoft.OpenSSH.Beta\n"
            "После установки перезапустите терминал."
        )
    return path


def check_ssh_version() -> Optional[str]:
    """Проверяем что версия >= 7.6 (нужен accept-new)."""
    try:
        result = subprocess.run(
            ["ssh", "-V"], capture_output=True, text=True,
            encoding="utf-8", errors="replace"
        )
        output = result.stderr or result.stdout
        m = re.search(r"OpenSSH_(\d+\.\d+)", output)
        if m:
            return m.group(1)
    except Exception:
        pass
    return None


def build_ssh_cmd(port: int = DEFAULT_MCP_PORT, subdomain: Optional[str] = None) -> str:
    version = check_ssh_version()
    # accept-new появился в OpenSSH 7.6
    try:
        parts = (version or "0.0").split(".", 1)
        major = float(parts[0])
        minor = float(parts[1]) if len(parts) > 1 else 0.0
        strict = "accept-new" if (major, minor) >= (7.6, 0) else "yes"
    except (ValueError, IndexError):
        strict = "accept-new"

    remote = f"{subdomain}:80:localhost:{port}" if subdomain else f"80:localhost:{port}"
    return (
        f"ssh -o ServerAliveInterval=60 "
        f"-o StrictHostKeyChecking={strict} "
        f"-R {remote} {SERVEO_HOST}"
    )

# ── F3: URL extractor ──────────────────────────────────────────────────────

def parse_serveo_url(line: str) -> Optional[str]:
    m = re.search(r"https?://[a-zA-Z0-9.-]+\.serveo\.net", line)
    return m.group(0) if m else None

# ── Gap fix: config auto-fill ──────────────────────────────────────────────

def fill_client_configs(public_url: str) -> None:
    """Replace placeholder or any previous serveo URL in all template configs."""
    pattern = re.compile(r"https://(?:YOUR_SUBDOMAIN|[a-zA-Z0-9-]+)\.serveo\.net")
    for path in CONFIGS_DIR.glob("*.json"):
        text = path.read_text(encoding="utf-8")
        updated = pattern.sub(public_url, text)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            logger.info("Updated %s → %s", path.name, public_url)

# ── C2: ServeoModeResolver ─────────────────────────────────────────────────

class ServeoModeResolver:
    def __init__(self, port: int = DEFAULT_MCP_PORT, subdomain: Optional[str] = None):
        self.port = port
        self.subdomain = subdomain

    def has_ssh_key(self) -> bool:
        ssh_dir = Path.home() / ".ssh"
        return any(ssh_dir.glob("id_*")) if ssh_dir.exists() else False

    def resolve(self) -> dict:
        mode = "named" if self.subdomain else ("keyed" if self.has_ssh_key() else "anonymous")
        cmd = build_ssh_cmd(self.port, self.subdomain)
        return {"mode": mode, "cmd": cmd, "warning": mode == "anonymous", "subdomain": self.subdomain}

def _build_cmd_args(cmd: str) -> list[str]:
    """На Windows используем shlex; на всех платформах — явный list."""
    import shlex
    return shlex.split(cmd, posix=(sys.platform != "win32"))


# ── C1: ServeoTunnelManager ────────────────────────────────────────────────

class ServeoTunnelManager:
    def __init__(self, port: int = DEFAULT_MCP_PORT, subdomain: Optional[str] = None):
        self.resolver = ServeoModeResolver(port, subdomain)
        self._proc: Optional[subprocess.Popen] = None
        self._url: Optional[str] = None
        self._stop_event = threading.Event()
        self._url_event = threading.Event()
        self._last_output: list[str] = []
        self._loop_thread: Optional[threading.Thread] = None

    @property
    def public_url(self) -> Optional[str]:
        return self._url

    def start(self, timeout: float = 15.0) -> Optional[str]:
        info = self.resolver.resolve()

        if not check_ssh_available():
            raise RuntimeError("ssh not found in PATH")

        if info["warning"]:
            logger.warning(
                "Anonymous Serveo tunnel: clients must send "
                "'serveo-skip-browser-warning: true' header"
            )

        self._stop_event.clear()
        self._url_event.clear()
        self._url = None
        self._last_output.clear()

        self._loop_thread = threading.Thread(
            target=self._tunnel_loop, args=(info,), daemon=True
        )
        self._loop_thread.start()

        if self._url_event.wait(timeout=timeout):
            return self._url

        self.stop()
        hint = " | ".join(self._last_output[-3:]) if self._last_output else "no output"
        raise TimeoutError(
            f"Serveo did not return a URL within {timeout}s. Last output: {hint}"
        )

    def _tunnel_loop(self, info: dict) -> None:
        attempt = 0
        while not self._stop_event.is_set():
            kwargs = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            proc = subprocess.Popen(
                _build_cmd_args(info["cmd"]),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs
            )
            self._proc = proc

            def _reader(p=proc) -> None:
                for line in p.stdout:
                    stripped = line.rstrip()
                    logger.debug("serveo: %s", stripped)
                    self._last_output.append(stripped)
                    if len(self._last_output) > 20:
                        self._last_output.pop(0)
                    url = parse_serveo_url(line)
                    if url:
                        self._url = url
                        fill_client_configs(url)
                        url_file = Path.home() / ".mnemostroma" / "serveo_url"
                        url_file.parent.mkdir(parents=True, exist_ok=True)
                        url_file.write_text(url, encoding="utf-8")
                        self._url_event.set()  # after all side-effects

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()

            proc.wait()
            reader.join(timeout=2)

            if self._stop_event.is_set():
                break

            self._url = None
            delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            logger.warning(
                "Serveo tunnel disconnected, reconnecting in %ds (attempt %d). "
                "Last output: %s",
                delay, attempt + 1,
                " | ".join(self._last_output[-3:]) if self._last_output else "no output",
            )
            attempt += 1
            self._stop_event.wait(timeout=delay)

    def stop(self) -> None:
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            if sys.platform == "win32":
                import signal
                ctrl_c = getattr(signal, "CTRL_C_EVENT", 0)
                try:
                    self._proc.send_signal(ctrl_c)
                    self._proc.wait(timeout=3)
                except (OSError, subprocess.TimeoutExpired):
                    self._proc.kill()
            else:
                self._proc.terminate()
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
        self._proc = None
        self._url = None
        url_file = Path.home() / ".mnemostroma" / "serveo_url"
        if url_file.exists():
            url_file.unlink()


# ── Wizard (used by CLI + installer) ──────────────────────────────────────

def wizard(
    port: int = DEFAULT_MCP_PORT,
    subdomain: Optional[str] = None,
    confirm: Optional[bool] = None,
) -> None:
    """Interactive wizard: launch tunnel, print client configs.

    Pass subdomain and confirm=True for headless / non-interactive use.
    """
    if not check_ssh_available():
        print("❌ ssh not found. Install OpenSSH first.")
        return

    interactive = subdomain is None and confirm is None

    if interactive:
        raw = input("Subdomain (leave blank for anonymous): ").strip()
        if raw and not re.fullmatch(r"[a-zA-Z0-9-]{1,63}", raw):
            print("❌ Invalid subdomain: only letters, digits, hyphens allowed (max 63 chars).")
            return
        subdomain = raw or None
    elif subdomain is not None and not re.fullmatch(r"[a-zA-Z0-9-]{1,63}", subdomain):
        raise ValueError(f"Invalid subdomain: {subdomain!r}")

    info = ServeoModeResolver(port, subdomain).resolve()

    print(f"\nMode    : {info['mode']}")
    print(f"Command : {info['cmd']}")
    if info["warning"]:
        print("⚠  Anonymous mode: add header  serveo-skip-browser-warning: true  to your MCP client")

    if interactive:
        if input("\nLaunch tunnel? [Y/n]: ").strip().lower() == "n":
            print("Aborted.")
            return
    elif not confirm:
        print("Aborted.")
        return

    mgr = ServeoTunnelManager(port, subdomain)
    print("Connecting to serveo.net…")
    try:
        url = mgr.start()
        if url:
            print(f"\n✓ Public MCP endpoint : {url}/mcp")
            print(f"  Client configs       : {CONFIGS_DIR}")
            print("  Press Ctrl+C to stop.")
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass
        else:
            print("❌ Failed to get URL from Serveo.")
    finally:
        mgr.stop()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    wizard()
