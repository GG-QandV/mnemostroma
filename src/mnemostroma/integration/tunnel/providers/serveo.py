# SPDX-License-Identifier: FSL-1.1-MIT
"""Serveo SSH tunnel provider for Mnemostroma.

Следует документации Serveo (https://serveo.net/docs):
- autossh -M 0 для авто-переподключения
- ServerAliveInterval=60 + ServerAliveCountMax=3
- ExitOnForwardFailure=yes
- StrictHostKeyChecking=accept-new
- ConnectTimeout=10 для быстрого определения отказа
- Порт 443 fallback если 22 не отвечает
- SSH username для детерминированного поддомена
- SSH key для keyed mode (более стабильный, чем anonymous)
"""

import contextlib
import hashlib
import logging
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger("mnemostroma.tunnel.providers.serveo")

SERVEO_HOST = "serveo.net"
SERVEO_PORT_22 = 22
SERVEO_PORT_443 = 443
DEFAULT_MCP_PORT = 8769
_BACKOFF = [0, 1, 2, 5, 15, 30, 60]
_CONNECT_TIMEOUT = 10


def check_ssh_available() -> str | None:
    return shutil.which("ssh")


def check_autossh_available() -> str | None:
    return shutil.which("autossh")


def _ssh_username() -> str:
    hostname = _get_hostname_slug()
    return f"mnemo-{hostname}"


def _get_hostname_slug() -> str:
    host = _try_hostname()
    return hashlib.sha256(host.encode()).hexdigest()[:8]


def _try_hostname() -> str:
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def _ssh_opts(ssh_port: int = SERVEO_PORT_22) -> str:
    opts = (
        f"-o ServerAliveInterval=60 "
        f"-o ServerAliveCountMax=3 "
        f"-o ExitOnForwardFailure=yes "
        f"-o StrictHostKeyChecking=accept-new "
        f"-o ConnectTimeout={_CONNECT_TIMEOUT} "
    )
    if ssh_port != SERVEO_PORT_22:
        opts += f"-p {ssh_port} "
    return opts


def build_ssh_cmd(
    port: int = DEFAULT_MCP_PORT,
    subdomain: str | None = None,
    ssh_port: int = SERVEO_PORT_22,
) -> str:
    remote = f"{subdomain}:80:localhost:{port}" if subdomain else f"80:localhost:{port}"
    user = _ssh_username()
    return f"ssh {_ssh_opts(ssh_port)}-R {remote} {user}@{SERVEO_HOST}"


def build_autossh_cmd(
    port: int = DEFAULT_MCP_PORT,
    subdomain: str | None = None,
    ssh_port: int = SERVEO_PORT_22,
) -> str:
    remote = f"{subdomain}:80:localhost:{port}" if subdomain else f"80:localhost:{port}"
    user = _ssh_username()
    return (
        f"autossh -M 0 "
        f"{_ssh_opts(ssh_port)}"
        f"-R {remote} {user}@{SERVEO_HOST}"
    )


def _best_cmd(
    port: int = DEFAULT_MCP_PORT,
    subdomain: str | None = None,
    ssh_port: int = SERVEO_PORT_22,
) -> str:
    if check_autossh_available():
        return build_autossh_cmd(port, subdomain, ssh_port)
    return build_ssh_cmd(port, subdomain, ssh_port)


def parse_serveo_url(line: str) -> str | None:
    if "console.serveo.net" in line:
        return None
    m = re.search(
        r"https?://[a-zA-Z0-9.-]+\.(?:serveo\.net|serveousercontent\.com)",
        line,
    )
    return m.group(0) if m else None


class ServeoModeResolver:
    def __init__(self, port: int = DEFAULT_MCP_PORT, subdomain: str | None = None):
        self.port = port
        self.subdomain = subdomain

    def has_ssh_key(self) -> bool:
        ssh_dir = Path.home() / ".ssh"
        return any(ssh_dir.glob("id_*")) if ssh_dir.exists() else False

    def resolve(self) -> dict:
        mode = (
            "named" if self.subdomain
            else "keyed" if self.has_ssh_key()
            else "anonymous"
        )
        cmd = _best_cmd(self.port, self.subdomain)
        return {
            "mode": mode,
            "cmd": cmd,
            "warning": mode == "anonymous",
            "subdomain": self.subdomain,
            "autossh": check_autossh_available() is not None,
        }


def _build_cmd_args(cmd: str) -> list[str]:
    return shlex.split(cmd, posix=(sys.platform != "win32"))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def _load_saved_proc() -> Any:
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
            is_valid = (
                "ssh" in name
                or "autossh" in name
                or any("serveo.net" in c for c in cmdline)
            )
            if is_valid:
                class _RestoredProc:
                    def __init__(self, pid):
                        self.pid = pid
                    def poll(self):
                        import psutil
                        return None if psutil.pid_exists(self.pid) else 0
                    def terminate(self):
                        import psutil
                        with contextlib.suppress(Exception):
                            psutil.Process(self.pid).terminate()
                    def kill(self):
                        import psutil
                        with contextlib.suppress(Exception):
                            psutil.Process(self.pid).kill()
                    def wait(self, timeout=None):
                        import psutil
                        with contextlib.suppress(Exception):
                            psutil.Process(self.pid).wait(timeout)
                    def send_signal(self, sig):
                        import psutil
                        with contextlib.suppress(Exception):
                            psutil.Process(self.pid).send_signal(sig)
                return _RestoredProc(pid)
    except Exception:
        pass
    with contextlib.suppress(Exception):
        pid_file.unlink(missing_ok=True)
    return None


class ServeoTunnelManager:
    def __init__(self, port: int = DEFAULT_MCP_PORT, subdomain: str | None = None):
        self.resolver = ServeoModeResolver(port, subdomain)
        self._proc: subprocess.Popen | None = _load_saved_proc()
        self._url: str | None = None
        self._stop_event = threading.Event()
        self._url_event = threading.Event()
        self._last_output: list[str] = []
        self._loop_thread: threading.Thread | None = None

    @property
    def public_url(self) -> str | None:
        return self._url

    def start(self, timeout: float = 15.0) -> str | None:
        info = self.resolver.resolve()

        if not check_ssh_available():
            raise RuntimeError("ssh not found in PATH")

        if info["warning"]:
            logger.warning(
                "Anonymous Serveo tunnel: clients must send "
                "'serveo-skip-browser-warning: true' header"
            )

        if info["autossh"]:
            logger.info("Using autossh for tunnel (auto-reconnect active)")
        else:
            logger.info("autossh not available; using plain ssh with reconnect loop")

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
        tried_443 = False

        while not self._stop_event.is_set():
            kwargs: dict[str, Any] = {}
            if sys.platform == "win32":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP

            cmd = info["cmd"]

            # Если порт 22 не отвечает — fallback на 443
            if attempt >= 2 and not tried_443:
                logger.info("Port 22 unreachable, falling back to port 443")
                if info["autossh"]:
                    cmd = build_autossh_cmd(
                        self.resolver.port,
                        self.resolver.subdomain,
                        ssh_port=SERVEO_PORT_443,
                    )
                else:
                    cmd = build_ssh_cmd(
                        self.resolver.port,
                        self.resolver.subdomain,
                        ssh_port=SERVEO_PORT_443,
                    )
                tried_443 = True

            proc = subprocess.Popen(
                _build_cmd_args(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                **kwargs,
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

                        # Если это переподключение — URL тот же, но перезаписываем
                        if not self._url_event.is_set():
                            self._url_event.set()

            reader = threading.Thread(target=_reader, daemon=True)
            reader.start()

            proc.wait()
            reader.join(timeout=2)

            if self._stop_event.is_set():
                break

            self._url = None
            delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            last_lines = (
                " | ".join(self._last_output[-3:])
                if self._last_output
                else "no output"
            )
            logger.warning(
                "Serveo tunnel disconnected, reconnecting in %ds (attempt %d). "
                "Last output: %s",
                delay, attempt + 1,
                last_lines,
            )
            self._last_output.clear()
            attempt += 1
            self._stop_event.wait(timeout=delay)

    def stop(self) -> None:
        self._stop_event.set()
        if self._proc and self._proc.poll() is None:
            if sys.platform == "win32":
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

        mnemo_dir = Path.home() / ".mnemostroma"
        (mnemo_dir / "serveo_url").unlink(missing_ok=True)
        (mnemo_dir / "tunnel_url").unlink(missing_ok=True)
        (mnemo_dir / "serveo_tunnel.pid").unlink(missing_ok=True)
