"""Unit tests for src/mnemostroma/integration/tunnel/providers/serveo.py"""
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from mnemostroma.integration.tunnel.providers.serveo import (
    _BACKOFF,
    ServeoModeResolver,
    ServeoTunnelManager,
    build_ssh_cmd,
    parse_serveo_url,
)


# ── parse_serveo_url ──────────────────────────────────────────────────────────

class TestParseServeoUrl:
    def test_https_in_forwarding_line(self):
        assert parse_serveo_url("Forwarding HTTP traffic from https://alex.serveo.net") == "https://alex.serveo.net"

    def test_serveousercontent_domain(self):
        assert parse_serveo_url("Forwarding HTTP traffic from https://xyz.serveousercontent.com") == "https://xyz.serveousercontent.com"

    def test_https_bare(self):
        assert parse_serveo_url("https://custom-123.serveo.net") == "https://custom-123.serveo.net"

    def test_http_accepted(self):
        # protocol lock fix: http:// is now accepted
        assert parse_serveo_url("http://alex.serveo.net") == "http://alex.serveo.net"

    def test_no_subdomain_returns_none(self):
        assert parse_serveo_url("https://serveo.net") is None

    def test_unrelated_line_returns_none(self):
        assert parse_serveo_url("some other output line") is None

    def test_empty_string_returns_none(self):
        assert parse_serveo_url("") is None

    def test_console_url_returns_none(self):
        assert parse_serveo_url("https://console.serveo.net") is None
        assert parse_serveo_url("some output with https://console.serveo.net in it") is None


# ── build_ssh_cmd ─────────────────────────────────────────────────────────────

class TestBuildSshCmd:
    def test_anonymous(self):
        cmd = build_ssh_cmd(8768)
        assert "-R 80:localhost:8768" in cmd
        assert "serveo.net" in cmd
        assert "StrictHostKeyChecking=accept-new" in cmd

    def test_named_subdomain(self):
        cmd = build_ssh_cmd(8765, "my-sub")
        assert "-R my-sub:80:localhost:8765" in cmd

    def test_server_alive_interval(self):
        assert "ServerAliveInterval=60" in build_ssh_cmd(8768)


# ── ServeoModeResolver ────────────────────────────────────────────────────────

class TestServeoModeResolver:
    def test_anonymous_no_key(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            res = ServeoModeResolver(8768).resolve()
        assert res["mode"] == "anonymous"
        assert res["warning"] is True

    def test_keyed_with_ssh_key(self, tmp_path):
        ssh = tmp_path / ".ssh"
        ssh.mkdir()
        (ssh / "id_rsa").write_text("dummy")
        with patch("pathlib.Path.home", return_value=tmp_path):
            res = ServeoModeResolver(8768).resolve()
        assert res["mode"] == "keyed"
        assert res["warning"] is False

    def test_named_subdomain(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            res = ServeoModeResolver(8768, "my-sub").resolve()
        assert res["mode"] == "named"
        assert res["subdomain"] == "my-sub"
        assert res["warning"] is False


# ── ServeoTunnelManager ───────────────────────────────────────────────────────

class TestServeoTunnelManager:
    def test_stop_noop_when_no_file(self, tmp_path):
        with patch("pathlib.Path.home", return_value=tmp_path):
            ServeoTunnelManager().stop()  # must not raise

    def test_start_returns_url(self, tmp_path):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        lines = [
            "some preamble\n",
            "Forwarding HTTP traffic from https://test.serveo.net\n",
        ]
        fake_proc.stdout = iter(lines)
        # Simulate process hanging (poll returns None indefinitely after lines run out)
        def fake_poll():
            return None
        fake_proc.poll = fake_poll

        stop_wait = threading.Event()
        fake_proc.wait.side_effect = lambda timeout=None: stop_wait.wait(timeout=timeout) or 0
        fake_proc.terminate.side_effect = lambda: stop_wait.set()
        fake_proc.kill.side_effect = lambda: stop_wait.set()

        with (
            patch("mnemostroma.integration.tunnel.providers.serveo.check_ssh_available", return_value="/usr/bin/ssh"),
            patch("subprocess.Popen", return_value=fake_proc),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            mgr = ServeoTunnelManager()
            url = mgr.start(timeout=5.0)
            time.sleep(0.1)  # Give reader thread time to process
            mgr.stop()

        assert url == "https://test.serveo.net"

    def test_start_timeout_includes_last_output(self, tmp_path):
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None

        def _slow_lines():
            yield "Connecting to serveo.net…\n"
            time.sleep(5)

        fake_proc.stdout = _slow_lines()

        with (
            patch("mnemostroma.integration.tunnel.providers.serveo.check_ssh_available", return_value="/usr/bin/ssh"),
            patch("subprocess.Popen", return_value=fake_proc),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            mgr = ServeoTunnelManager()
            with pytest.raises(TimeoutError, match="Connecting to serveo"):
                mgr.start(timeout=0.5)


# ── ServeoTunnelManager reconnect ────────────────────────────────────────────

class TestServeoTunnelManagerReconnect:
    def _proc(self, lines):
        p = MagicMock()
        p.poll.return_value = None
        stop_wait = threading.Event()

        def stdout_gen():
            for line in lines:
                yield line
            time.sleep(0.1)
            stop_wait.set()

        p.stdout = stdout_gen()
        p.wait.side_effect = lambda timeout=None: stop_wait.wait(timeout=timeout) or 0
        p.terminate.side_effect = lambda: stop_wait.set()
        p.kill.side_effect = lambda: stop_wait.set()
        return p

    def test_reconnect_starts_new_process(self, tmp_path):
        """After SSH process dies, _tunnel_loop spawns a second Popen."""
        proc1 = self._proc(["Forwarding HTTP traffic from https://first.serveo.net\n"])
        proc2 = self._proc([])
        proc2_started = threading.Event()
        calls = []

        def popen_side(cmd, **kw):
            calls.append(len(calls) + 1)
            if len(calls) == 1:
                return proc1
            proc2_started.set()
            return proc2

        with (
            patch("mnemostroma.integration.tunnel.providers.serveo.check_ssh_available", return_value="/usr/bin/ssh"),
            patch("subprocess.Popen", side_effect=popen_side),
            patch("mnemostroma.integration.tunnel.providers.serveo._BACKOFF", [0.01]),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            mgr = ServeoTunnelManager()
            url = mgr.start(timeout=3.0)
            assert url == "https://first.serveo.net"
            assert proc2_started.wait(timeout=3.0), "Second Popen never called"
            mgr.stop()

        assert len(calls) == 2

    def test_stop_interrupts_backoff(self, tmp_path):
        """stop() during reconnect sleep wakes the loop immediately."""
        proc1 = self._proc(["Forwarding HTTP traffic from https://first.serveo.net\n"])

        with (
            patch("mnemostroma.integration.tunnel.providers.serveo.check_ssh_available", return_value="/usr/bin/ssh"),
            patch("subprocess.Popen", return_value=proc1),
            patch("mnemostroma.integration.tunnel.providers.serveo._BACKOFF", [60]),  # would block 60s without stop()
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            mgr = ServeoTunnelManager()
            mgr.start(timeout=3.0)
            time.sleep(0.1)  # let proc1 die and enter backoff

            t0 = time.monotonic()
            mgr.stop()
            mgr._loop_thread.join(timeout=2.0)

        assert time.monotonic() - t0 < 1.0
        assert not mgr._loop_thread.is_alive()

    def test_url_updated_on_reconnect(self, tmp_path):
        """After reconnect, public_url property reflects the new URL."""
        proc1 = self._proc(["Forwarding HTTP traffic from https://first.serveo.net\n"])

        # proc2 blocks on wait() until we release it — gives us time to assert the URL
        proc2_release = threading.Event()
        proc2 = MagicMock()
        proc2.poll.return_value = None
        proc2.stdout = iter(["Forwarding HTTP traffic from https://second.serveo.net\n"])
        proc2.wait.side_effect = lambda *a, **kw: proc2_release.wait(timeout=10) or 0

        calls = []

        def popen_side(cmd, **kw):
            calls.append(len(calls) + 1)
            return proc1 if len(calls) == 1 else proc2

        with (
            patch("mnemostroma.integration.tunnel.providers.serveo.check_ssh_available", return_value="/usr/bin/ssh"),
            patch("subprocess.Popen", side_effect=popen_side),
            patch("mnemostroma.integration.tunnel.providers.serveo._BACKOFF", [0.01]),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            mgr = ServeoTunnelManager()
            mgr.start(timeout=3.0)

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if mgr.public_url == "https://second.serveo.net":
                    break
                time.sleep(0.02)

            assert mgr.public_url == "https://second.serveo.net"
            proc2_release.set()
            mgr.stop()

    def test_public_url_none_during_reconnect(self, tmp_path):
        """public_url becomes None after process dies, before new URL arrives."""
        proc1 = self._proc(["Forwarding HTTP traffic from https://first.serveo.net\n"])
        proc2 = self._proc([])  # second proc emits nothing
        calls = []

        def popen_side(cmd, **kw):
            calls.append(len(calls) + 1)
            return proc1 if len(calls) == 1 else proc2

        with (
            patch("mnemostroma.integration.tunnel.providers.serveo.check_ssh_available", return_value="/usr/bin/ssh"),
            patch("subprocess.Popen", side_effect=popen_side),
            patch("mnemostroma.integration.tunnel.providers.serveo._BACKOFF", [0.01]),
            patch("pathlib.Path.home", return_value=tmp_path),
        ):
            mgr = ServeoTunnelManager()
            mgr.start(timeout=3.0)

            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if len(calls) >= 2:
                    break
                time.sleep(0.01)

            assert len(calls) == 2
            time.sleep(0.05)  # proc2 runs but emits nothing
            assert mgr.public_url is None
            mgr.stop()

    def test_backoff_caps_at_last_value(self):
        """Backoff delay doesn't exceed _BACKOFF[-1] regardless of attempt count."""
        for attempt in range(len(_BACKOFF) + 10):
            delay = _BACKOFF[min(attempt, len(_BACKOFF) - 1)]
            assert delay <= _BACKOFF[-1]
        assert _BACKOFF[-1] == 60
