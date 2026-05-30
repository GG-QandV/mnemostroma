# SPDX-License-Identifier: FSL-1.1-MIT
"""Serveo SSH tunnel provider for Mnemostroma."""

import logging
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Any

logger = logging.getLogger("mnemostroma.tunnel.providers.serveo")

SERVEO_HOST = "serveo.net"
DEFAULT_MCP_PORT = 8769
_BACKOFF = [5, 15, 30, 60]  # reconnect delays in seconds


def check_ssh_available() -> Optional[str]:
    """Check if ssh binary is available."""
    return shutil.which("ssh")


def build_ssh_cmd(port: int = DEFAULT_MCP_PORT, subdomain: Optional[str] = None) -> str:
    """Build SSH command for Serveo tunnel."""
    remote = f"{subdomain}:80:localhost:{port}" if subdomain else f"80:localhost:{port}"
    return (
        f"ssh -o ServerAliveInterval=60 "
        f"-o StrictHostKeyChecking=accept-new "
        f"-R {remote} {SERVEO_HOST}"
    )


def parse_serveo_url(line: str) -> Optional[str]:
    """Extract Serveo URL from SSH output."""
    if "console.serveo.net" in line:
        return None
    m = re.search(r"https?://[a-zA-Z0-9.-]+\.(?:serveo\.net|serveousercontent\.com)", line)
    return m.group(0) if m else None


class ServeoModeResolver:
    """Determine Serveo mode: anonymous, keyed, or named."""

    def __init__(self, port: int = DEFAULT_MCP_PORT, subdomain: Optional[str] = None):
        self.port = port
        self.subdomain = subdomain

    def has_ssh_key(self) -> bool:
        """Check if SSH key exists."""
        ssh_dir = Path.home() / ".ssh"
        return any(ssh_dir.glob("id_*")) if ssh_dir.exists() else False

    def resolve(self) -> dict:
        """Resolve mode and build SSH command."""
        mode = "named" if self.subdomain else ("keyed" if self.has_ssh_key() else "anonymous")
        cmd = build_ssh_cmd(self.port, self.subdomain)
        return {"mode": mode, "cmd": cmd, "warning": mode == "anonymous", "subdomain": self.subdomain}


def _build_cmd_args(cmd: str) -> list[str]:
    """На Windows используем shlex; на всех платформах — явный list."""
    import shlex
    import sys
    return shlex.split(cmd, posix=(sys.platform != "win32"))


def _atomic_write(path: Path, content: str) -> None:
    """Пишет файл атомарно с использованием временного файла рядом."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _load_saved_proc() -> Any:
    """Пытается восстановить handle на живой ssh/serveo процесс."""
    pid_file = Path.home() / ".mnemostroma" / "serveo_tunnel.pid"
    if not pid_file.exists():
        return None
    try:
        import psutil
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        if psutil.pid_exists(pid):
            proc = psutil.Process(pid)
            name = proc.name().lower()
            cmdline = proc.cmdline()
            is_valid = "ssh" in name or any("serveo.net" in c for c in cmdline)
            if is_valid:
                class _RestoredProc:
                    def __init__(self, pid):
                        self.pid = pid
                    def poll(self):
                        import psutil
                        return None if psutil.pid_exists(self.pid) else 0
                    def terminate(self):
                        import psutil
                        try:
                            psutil.Process(self.pid).terminate()
                        except Exception:
                            pass
                    def kill(self):
                        import psutil
                        try:
                            psutil.Process(self.pid).kill()
                        except Exception:
                            pass
                    def wait(self, timeout=None):
                        import psutil
                        try:
                            psutil.Process(self.pid).wait(timeout)
                        except Exception:
                            pass
                    def send_signal(self, sig):
                        import psutil
                        try:
                            psutil.Process(self.pid).send_signal(sig)
                        except Exception:
                            pass
                return _RestoredProc(pid)
    except Exception:
        pass
    try:
        pid_file.unlink(missing_ok=True)
    except Exception:
        pass
    return None


class ServeoTunnelManager:
    """Manages Serveo SSH tunnel with auto-reconnect."""

    def __init__(self, port: int = DEFAULT_MCP_PORT, subdomain: Optional[str] = None):
        self.resolver = ServeoModeResolver(port, subdomain)
        self._proc: Optional[subprocess.Popen] = _load_saved_proc()
        self._url: Optional[str] = None
        self._stop_event = threading.Event()
        self._url_event = threading.Event()
        self._last_output: list[str] = []
        self._loop_thread: Optional[threading.Thread] = None

    @property
    def public_url(self) -> Optional[str]:
        """Get current tunnel URL."""
        return self._url

    def start(self, timeout: float = 15.0) -> Optional[str]:
        """Start tunnel and wait for URL."""
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
        """Auto-reconnect loop with backoff."""
        import sys
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
            try:
                pid_file = Path.home() / ".mnemostroma" / "serveo_tunnel.pid"
                pid_file.parent.mkdir(parents=True, exist_ok=True)
                pid_file.write_text(str(proc.pid), encoding="utf-8")
            except Exception:
                pass

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
                        url_file = Path.home() / ".mnemostroma" / "serveo_url"
                        _atomic_write(url_file, url)
                        _atomic_write(Path.home() / ".mnemostroma" / "tunnel_url", url)
                        self._url_event.set()

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
        """Stop tunnel and cleanup."""
        import sys
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

        # Очистка фантомных файлов
        mnemo_dir = Path.home() / ".mnemostroma"
        (mnemo_dir / "serveo_url").unlink(missing_ok=True)
        (mnemo_dir / "tunnel_url").unlink(missing_ok=True)
        (mnemo_dir / "serveo_tunnel.pid").unlink(missing_ok=True)
