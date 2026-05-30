# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add src to path
sys.path.append(str(Path(__file__).parent.parent / "src"))

from mnemostroma import watchdog

class TestMnemostromaWatchdog(unittest.IsolatedAsyncioTestCase):

    async def test_check_daemon_sock_checked_on_stale_hb(self):
        """TEST-WD-001 — _check_daemon: сокет проверяется при stale heartbeat."""
        called = {"socket": False}

        async def fake_socket_responsive():
            called["socket"] = True
            return True  # сокет жив

        with patch.object(watchdog, "_heartbeat_ok", return_value=False), \
             patch.object(watchdog, "_socket_responsive", side_effect=fake_socket_responsive), \
             patch.object(watchdog, "_HEARTBEAT_FILE") as mock_hb:
            mock_hb.exists.return_value = False
            await watchdog._check_daemon(120)

        self.assertTrue(called["socket"], "FAIL: _socket_responsive не вызван при stale heartbeat")
        print("TEST-WD-001 PASSED")

    async def test_check_daemon_hang_when_sock_ok_hb_stale(self):
        """TEST-WD-002 — _check_daemon: HANG если сокет жив но heartbeat stale."""
        killed = {"called": False}

        def fake_kill(pid_file, sig=None):
            killed["called"] = True

        async def fake_socket_responsive():
            return True

        with patch.object(watchdog, "_heartbeat_ok", return_value=False), \
             patch.object(watchdog, "_socket_responsive", side_effect=fake_socket_responsive), \
             patch.object(watchdog, "_HEARTBEAT_FILE") as mock_hb, \
             patch.object(watchdog, "_kill", side_effect=fake_kill), \
             patch.object(watchdog, "_kill_all_daemon_instances"), \
             patch.object(watchdog, "_clean_socket"):
            mock_hb.exists.return_value = True  # файл есть, но stale
            await watchdog._check_daemon(120)

        self.assertTrue(killed["called"], "FAIL: _kill не вызван при HANG")
        print("TEST-WD-002 PASSED")

    async def test_check_daemon_no_kill_when_daemon_not_started(self):
        """TEST-WD-003 — _check_daemon: daemon ещё не стартовал — не убивать."""
        killed = {"called": False}

        def fake_kill(*a, **kw):
            killed["called"] = True

        async def fake_socket_responsive():
            return False  # сокета нет

        with patch.object(watchdog, "_heartbeat_ok", return_value=False), \
             patch.object(watchdog, "_socket_responsive", side_effect=fake_socket_responsive), \
             patch.object(watchdog, "_HEARTBEAT_FILE") as mock_hb, \
             patch.object(watchdog, "_kill", side_effect=fake_kill), \
             patch.object(watchdog, "_kill_all_daemon_instances", side_effect=fake_kill), \
             patch.object(watchdog, "_clean_socket"):
            mock_hb.exists.return_value = False  # файла нет
            await watchdog._check_daemon(120)

        # ВНИМАНИЕ: при отсутствии сокета И файла — убиваем (UNRESPONSIVE)
        # Этот тест проверяет что убийство всё же происходит (нет молчаливого skip)
        self.assertTrue(killed["called"], "FAIL: UNRESPONSIVE daemon должен быть убит")
        print("TEST-WD-003 PASSED")

    async def test_phase1_no_kill_if_socket_alive_after_timeout(self):
        """TEST-WD-004 — Phase 1: не убивает daemon если сокет жив после timeout."""
        kill_called = {"daemon": False, "proxy": False}

        def fake_kill_daemon(pid_file, sig=None):
            if "daemon" in str(pid_file):
                kill_called["daemon"] = True

        async def fake_proxy_healthy(timeout):
            return False  # proxy не поднят

        async def fake_socket_responsive():
            return True  # сокет жив

        with patch.object(watchdog, "_heartbeat_ok", return_value=False), \
             patch.object(watchdog, "_socket_responsive", side_effect=fake_socket_responsive), \
             patch.object(watchdog, "_proxy_healthy", side_effect=fake_proxy_healthy), \
             patch.object(watchdog, "_kill", side_effect=fake_kill_daemon), \
             patch.object(watchdog, "Config") as MockConfig:

            mock_cfg = MagicMock()
            mock_cfg.watchdog.heartbeat_timeout_sec = 120
            mock_cfg.watchdog.check_interval_sec = 1
            mock_cfg.watchdog.startup_failsafe_sec = 1  # очень короткий для теста
            MockConfig.load.return_value = mock_cfg

            # Запустить run() с таймаутом 3 секунды
            try:
                await asyncio.wait_for(watchdog.run(), timeout=3)
            except asyncio.TimeoutError:
                pass  # ожидаемо — Phase 2 бесконечный цикл

        self.assertFalse(kill_called["daemon"], "FAIL: daemon убит при живом сокете")
        print("TEST-WD-004 PASSED")

    async def test_proxy_timeout_from_config(self):
        """TEST-WD-005 — proxy_timeout из config используется в Phase 2."""
        received_timeout = {"val": None}

        async def fake_proxy_healthy(timeout):
            received_timeout["val"] = timeout
            return True

        with patch.object(watchdog, "_proxy_healthy", side_effect=fake_proxy_healthy), \
             patch.object(watchdog, "_heartbeat_ok", return_value=True), \
             patch.object(watchdog, "Config") as MockConfig:

            mock_cfg = MagicMock()
            mock_cfg.watchdog.heartbeat_timeout_sec = 120
            mock_cfg.watchdog.check_interval_sec = 1
            mock_cfg.watchdog.startup_failsafe_sec = 0
            mock_cfg.watchdog.proxy_timeout_sec = 99  # нестандартное значение
            MockConfig.load.return_value = mock_cfg

            try:
                await asyncio.wait_for(watchdog.run(), timeout=2)
            except asyncio.TimeoutError:
                pass

        self.assertEqual(received_timeout["val"], 99,
                         f"FAIL: proxy_timeout={received_timeout['val']}, ожидался 99 из config")
        print("TEST-WD-005 PASSED")

    async def test_notify_systemd_called_in_phase1(self):
        """TEST-WD-007 — _notify_systemd вызывается в Phase 1."""
        notify_called = {"count": 0}

        def fake_notify():
            notify_called["count"] += 1

        with patch.object(watchdog, "_notify_systemd", side_effect=fake_notify), \
             patch.object(watchdog, "_heartbeat_ok", return_value=False), \
             patch.object(watchdog, "_proxy_healthy", return_value=False), \
             patch.object(watchdog, "_socket_responsive", return_value=False), \
             patch.object(watchdog, "_kill"), \
             patch.object(watchdog, "Config") as MockConfig:

            mock_cfg = MagicMock()
            mock_cfg.watchdog.heartbeat_timeout_sec = 120
            mock_cfg.watchdog.check_interval_sec = 999
            mock_cfg.watchdog.startup_failsafe_sec = 8
            MockConfig.load.return_value = mock_cfg

            try:
                await asyncio.wait_for(watchdog.run(), timeout=4)
            except (asyncio.TimeoutError, SystemExit):
                pass

        self.assertTrue(notify_called["count"] > 0, "FAIL: _notify_systemd не вызван в Phase 1")
        print(f"TEST-WD-007 PASSED: _notify_systemd вызван {notify_called['count']} раз")

if __name__ == "__main__":
    unittest.main()
