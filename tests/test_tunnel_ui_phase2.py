# SPDX-License-Identifier: FSL-1.1-MIT
"""
Sprint+4 — Tunnel UI Phase 2 tests.
27 тестов в 5 классах согласно спеке SPEC Tunnel UI - Consolidated.md.
"""
import asyncio
import os
import stat
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_mnemo(tmp_path, monkeypatch):
    """Изолированная ~/.mnemostroma в tmp_path."""
    mnemo = tmp_path / ".mnemostroma"
    mnemo.mkdir()
    return mnemo


# ═══════════════════════════════════════════════════════════════════════════════
# 1. TestTunnelState — 5 тестов
# ═══════════════════════════════════════════════════════════════════════════════

class TestTunnelState:

    def test_get_url_returns_content(self, tmp_mnemo, monkeypatch):
        """Файл tunnel_url существует → возвращает URL."""
        from mnemostroma.integration.tunnel import state
        url_file = tmp_mnemo / "tunnel_url"
        url_file.write_text("https://mnemo-abc123.serveo.net", encoding="utf-8")
        monkeypatch.setattr(state, "_TUNNEL_URL_FILE", url_file)

        assert state.get_tunnel_url() == "https://mnemo-abc123.serveo.net"

    def test_get_url_file_not_found(self, tmp_mnemo, monkeypatch):
        """Файл tunnel_url не существует → None."""
        from mnemostroma.integration.tunnel import state
        monkeypatch.setattr(state, "_TUNNEL_URL_FILE", tmp_mnemo / "tunnel_url")

        assert state.get_tunnel_url() is None

    def test_get_url_empty_file(self, tmp_mnemo, monkeypatch):
        """Файл tunnel_url пустой → None."""
        from mnemostroma.integration.tunnel import state
        url_file = tmp_mnemo / "tunnel_url"
        url_file.write_text("   \n", encoding="utf-8")
        monkeypatch.setattr(state, "_TUNNEL_URL_FILE", url_file)

        assert state.get_tunnel_url() is None

    def test_get_url_os_error_returns_none(self, tmp_mnemo, monkeypatch):
        """OSError при чтении → None (без исключения наружу)."""
        from mnemostroma.integration.tunnel import state
        url_file = tmp_mnemo / "tunnel_url"
        url_file.write_text("https://mnemo-abc.serveo.net", encoding="utf-8")
        url_file.chmod(0o000)
        monkeypatch.setattr(state, "_TUNNEL_URL_FILE", url_file)

        try:
            result = state.get_tunnel_url()
            assert result is None
        finally:
            url_file.chmod(0o644)

    def test_get_token_delegates_to_token_module(self, monkeypatch):
        """get_tunnel_token() возвращает результат из tunnel.token.get_tunnel_token."""
        from mnemostroma.integration.tunnel import state
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.token.get_tunnel_token",
            lambda: "tok-xyz-123",
        )
        assert state.get_tunnel_token() == "tok-xyz-123"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. TestTunnelObserveHandlers — 8 тестов
# ═══════════════════════════════════════════════════════════════════════════════

def _make_observe_test_app():
    from mnemostroma.integration.tunnel.observe_handlers import (
        handle_tunnel_status,
        handle_tunnel_start,
        handle_tunnel_stop,
    )
    return Starlette(routes=[
        Route("/tunnel/status", endpoint=handle_tunnel_status, methods=["GET"]),
        Route("/tunnel/start",  endpoint=handle_tunnel_start,  methods=["POST"]),
        Route("/tunnel/stop",   endpoint=handle_tunnel_stop,   methods=["POST"]),
    ])


_SAMPLE_ROUTES = {
    "/mcp": {"auth": ["none"], "client": "perplexity"},
    "/mcp/grok": {"auth": ["bearer"], "client": "grok"},
}


class TestTunnelObserveHandlers:

    @pytest.fixture(autouse=True)
    def client(self):
        self._client = TestClient(_make_observe_test_app(), raise_server_exceptions=True)

    def test_status_stopped(self, monkeypatch):
        """Туннель не запущен → running=False, chats=[]."""
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_url", lambda: None
        )
        r = self._client.get("/tunnel/status")
        assert r.status_code == 200
        data = r.json()
        assert data["running"] is False
        assert data["url"] is None
        assert data["chats"] == []

    def test_status_running_empty_routes(self, monkeypatch):
        """Туннель запущен, routes={} → running=True, chats=[]."""
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_url",
            lambda: "https://mnemo-x.serveo.net",
        )
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_token", lambda: None
        )
        mock_cfg = MagicMock()
        mock_cfg.routes = {}
        with patch("mnemostroma.integration.mcp_oauth_adapter.load_route_config", return_value=mock_cfg):
            r = self._client.get("/tunnel/status")
        data = r.json()
        assert data["running"] is True
        assert data["chats"] == []

    def test_status_chats_structure(self, monkeypatch):
        """chats[] содержит обязательные поля для каждого роута."""
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_url",
            lambda: "https://mnemo-x.serveo.net",
        )
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_token", lambda: None
        )
        mock_cfg = MagicMock()
        mock_cfg.routes = {"/mcp": {"auth": ["none"], "client": "perplexity"}}
        with patch("mnemostroma.integration.mcp_oauth_adapter.load_route_config", return_value=mock_cfg):
            r = self._client.get("/tunnel/status")
        chat = r.json()["chats"][0]
        for field in ("client", "label", "icon", "full_url", "token", "hint", "needs_token"):
            assert field in chat, f"Поле '{field}' отсутствует в chats[0]"
        assert chat["full_url"] == "https://mnemo-x.serveo.net/mcp"

    def test_status_needs_token_true_for_grok(self, monkeypatch):
        """Grok с auth=[bearer] → needs_token=True, token в ответе."""
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_url",
            lambda: "https://mnemo-x.serveo.net",
        )
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_token",
            lambda: "secret-token",
        )
        mock_cfg = MagicMock()
        mock_cfg.routes = {"/mcp/grok": {"auth": ["bearer"], "client": "grok"}}
        with patch("mnemostroma.integration.mcp_oauth_adapter.load_route_config", return_value=mock_cfg):
            r = self._client.get("/tunnel/status")
        chat = r.json()["chats"][0]
        assert chat["needs_token"] is True
        assert chat["token"] == "secret-token"

    def test_status_needs_token_false_without_bearer(self, monkeypatch):
        """Grok но auth без 'bearer' → needs_token=False, token=None."""
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_url",
            lambda: "https://mnemo-x.serveo.net",
        )
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_token",
            lambda: "secret-token",
        )
        mock_cfg = MagicMock()
        mock_cfg.routes = {"/mcp/grok": {"auth": ["oauth"], "client": "grok"}}
        with patch("mnemostroma.integration.mcp_oauth_adapter.load_route_config", return_value=mock_cfg):
            r = self._client.get("/tunnel/status")
        chat = r.json()["chats"][0]
        assert chat["needs_token"] is False
        assert chat["token"] is None

    def test_status_routes_error_returns_error_field(self, monkeypatch):
        """load_route_config raises → {"error": "routes_unavailable"} в ответе."""
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_url",
            lambda: "https://mnemo-x.serveo.net",
        )
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.observe_handlers.get_tunnel_token", lambda: None
        )
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.load_route_config",
            side_effect=RuntimeError("file missing"),
        ):
            r = self._client.get("/tunnel/status")
        data = r.json()
        assert data["running"] is True
        assert data["error"] == "routes_unavailable"

    def test_start_launches_subprocess(self, monkeypatch):
        """POST /tunnel/start → started=True, asyncio.create_subprocess_exec вызван."""
        mock_proc = AsyncMock()
        with patch(
            "mnemostroma.integration.tunnel.observe_handlers.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            r = self._client.post("/tunnel/start")
        assert r.status_code == 200
        assert r.json()["started"] is True
        mock_exec.assert_awaited_once()
        args = mock_exec.call_args[0]
        assert args[-3:] == ("mnemostroma", "tunnel", "start")

    def test_stop_launches_subprocess(self, monkeypatch):
        """POST /tunnel/stop → stopped=True, asyncio.create_subprocess_exec вызван."""
        mock_proc = AsyncMock()
        with patch(
            "mnemostroma.integration.tunnel.observe_handlers.asyncio.create_subprocess_exec",
            return_value=mock_proc,
        ) as mock_exec:
            r = self._client.post("/tunnel/stop")
        assert r.status_code == 200
        assert r.json()["stopped"] is True
        mock_exec.assert_awaited_once()
        args = mock_exec.call_args[0]
        assert args[-3:] == ("mnemostroma", "tunnel", "stop")


# ═══════════════════════════════════════════════════════════════════════════════
# 3. TestTunnelChatMeta — 4 теста
# ═══════════════════════════════════════════════════════════════════════════════

class TestTunnelChatMeta:

    def test_known_client_perplexity(self):
        """get_meta('perplexity') → правильные label/icon/needs_token."""
        from mnemostroma.integration.tunnel.ui_meta import get_meta
        meta = get_meta("perplexity")
        assert meta["label"] == "Perplexity"
        assert meta["icon"] == "🔍"
        assert meta["needs_token"] is False

    def test_known_client_grok_needs_token(self):
        """get_meta('grok') → needs_token=True."""
        from mnemostroma.integration.tunnel.ui_meta import get_meta
        meta = get_meta("grok")
        assert meta["needs_token"] is True

    def test_unknown_client_fallback(self):
        """get_meta('newchat') → label=Newchat, icon=🔗, needs_token=False."""
        from mnemostroma.integration.tunnel.ui_meta import get_meta
        meta = get_meta("newchat")
        assert meta["label"] == "Newchat"
        assert meta["icon"] == "🔗"
        assert meta["needs_token"] is False

    def test_only_grok_needs_token(self):
        """Только grok имеет needs_token=True среди всех известных клиентов."""
        from mnemostroma.integration.tunnel.ui_meta import CHAT_UI_META
        token_clients = [k for k, v in CHAT_UI_META.items() if v["needs_token"]]
        assert token_clients == ["grok"]


# ═══════════════════════════════════════════════════════════════════════════════
# 4. TestManagerFlatFile — 3 теста
# ═══════════════════════════════════════════════════════════════════════════════

class TestManagerFlatFile:

    def test_writes_canonical_file(self, tmp_mnemo, monkeypatch):
        """_save_tunnel_url пишет tunnel_urls/user-{subdomain}.txt."""
        from mnemostroma.integration.tunnel import manager
        monkeypatch.setattr(manager, "MNEMO_DIR", tmp_mnemo)
        monkeypatch.setattr(manager, "TUNNEL_URLS_DIR", tmp_mnemo / "tunnel_urls")

        manager._save_tunnel_url("my-sub", "https://mnemo-my-sub.serveo.net")

        canonical = tmp_mnemo / "tunnel_urls" / "user-my-sub.txt"
        assert canonical.exists()
        assert canonical.read_text(encoding="utf-8") == "https://mnemo-my-sub.serveo.net"

    def test_writes_flat_alias(self, tmp_mnemo, monkeypatch):
        """_save_tunnel_url пишет tunnel_url flat alias."""
        from mnemostroma.integration.tunnel import manager
        monkeypatch.setattr(manager, "MNEMO_DIR", tmp_mnemo)
        monkeypatch.setattr(manager, "TUNNEL_URLS_DIR", tmp_mnemo / "tunnel_urls")

        manager._save_tunnel_url("my-sub", "https://mnemo-my-sub.serveo.net")

        flat = tmp_mnemo / "tunnel_url"
        assert flat.exists()
        assert flat.read_text(encoding="utf-8") == "https://mnemo-my-sub.serveo.net"

    def test_flat_alias_no_tmp_leftover(self, tmp_mnemo, monkeypatch):
        """После записи tmp-файл не остаётся (атомарная замена через rename)."""
        from mnemostroma.integration.tunnel import manager
        monkeypatch.setattr(manager, "MNEMO_DIR", tmp_mnemo)
        monkeypatch.setattr(manager, "TUNNEL_URLS_DIR", tmp_mnemo / "tunnel_urls")

        manager._save_tunnel_url("my-sub", "https://mnemo-my-sub.serveo.net")

        tmp_file = tmp_mnemo / "tunnel_url.tmp"
        assert not tmp_file.exists(), ".tmp файл не должен оставаться после rename"


# ═══════════════════════════════════════════════════════════════════════════════
# 5. TestTrayTunnelMenu — 7 тестов
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture(scope="class")
def qt_app():
    """QApplication для всего класса. offscreen — без дисплея."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


class TestTrayTunnelMenu:

    @pytest.fixture(autouse=True)
    def _qt(self, qt_app):
        self._app = qt_app

    # ── TunnelUrlWatcher ──────────────────────────────────────────────────────

    def test_watcher_init_stores_current_url(self, monkeypatch):
        """TunnelUrlWatcher.__init__ запоминает начальный URL."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: "https://mnemo-z.serveo.net")
        tray_icon = MagicMock()
        watcher = tray_mod.TunnelUrlWatcher(tray_icon)
        assert watcher._last_url == "https://mnemo-z.serveo.net"

    def test_watcher_check_notifies_on_url_change(self, monkeypatch):
        """check() вызывает showMessage когда URL изменился."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: "https://mnemo-old.serveo.net")
        tray_icon = MagicMock()
        watcher = tray_mod.TunnelUrlWatcher(tray_icon)

        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: "https://mnemo-new.serveo.net")
        watcher.check()

        tray_icon.showMessage.assert_called_once()
        args = tray_icon.showMessage.call_args[0]
        assert "mnemo-new" in args[1]

    def test_watcher_check_no_notify_same_url(self, monkeypatch):
        """check() не вызывает showMessage если URL не изменился."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: "https://mnemo-x.serveo.net")
        tray_icon = MagicMock()
        watcher = tray_mod.TunnelUrlWatcher(tray_icon)

        watcher.check()  # URL тот же

        tray_icon.showMessage.assert_not_called()

    def test_watcher_check_resets_on_tunnel_stop(self, monkeypatch):
        """check() сбрасывает _last_url в None когда туннель остановлен."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: "https://mnemo-x.serveo.net")
        tray_icon = MagicMock()
        watcher = tray_mod.TunnelUrlWatcher(tray_icon)

        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: None)
        watcher.check()

        assert watcher._last_url is None

    # ── _populate_tunnel_submenu ──────────────────────────────────────────────
    # DaemonTrayApp создаёт QSystemTrayIcon — не поддерживается в offscreen.
    # Тестируем _populate_tunnel_submenu как unbound-метод на минимальном stub-объекте
    # с реальным QMenu (QMenu работает в offscreen без трей-иконки).

    def _make_stub(self, monkeypatch, url=None, token=None, routes=None):
        """Stub с _tunnel_submenu = QMenu, без QSystemTrayIcon."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        from PyQt6.QtWidgets import QMenu

        monkeypatch.setattr(tray_mod, "get_tunnel_url", lambda: url)
        monkeypatch.setattr(tray_mod, "get_tunnel_token", lambda: token)

        if routes is not None:
            mock_cfg = MagicMock()
            mock_cfg.routes = routes
            monkeypatch.setattr(
                "mnemostroma.integration.mcp_oauth_adapter.load_route_config",
                lambda: mock_cfg,
            )

        class _Stub:
            _tunnel_submenu = QMenu("🌐 Tunnel")
            def _stop_tunnel_with_feedback(self):
                pass

        return _Stub()

    def test_populate_stopped_shows_start_action(self, monkeypatch):
        """Туннель не запущен → меню содержит 'Start Tunnel'."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        stub = self._make_stub(monkeypatch, url=None)
        tray_mod.DaemonTrayApp._populate_tunnel_submenu(stub)

        labels = [a.text() for a in stub._tunnel_submenu.actions()]
        assert any("Start Tunnel" in l for l in labels), f"Start Tunnel не найден: {labels}"

    def test_populate_active_shows_url_and_stop(self, monkeypatch):
        """Туннель запущен → меню содержит URL и Stop Tunnel."""
        import mnemostroma.tools.tray_pyqt as tray_mod
        routes = {"/mcp": {"auth": ["none"], "client": "perplexity"}}
        stub = self._make_stub(
            monkeypatch,
            url="https://mnemo-abc.serveo.net",
            token=None,
            routes=routes,
        )
        tray_mod.DaemonTrayApp._populate_tunnel_submenu(stub)

        labels = [a.text() for a in stub._tunnel_submenu.actions()]
        assert any("mnemo-abc" in l for l in labels), f"URL не найден: {labels}"
        assert any("Stop Tunnel" in l for l in labels), f"Stop Tunnel не найден: {labels}"

    def test_copy_lambda_closure_captures_correct_url(self, monkeypatch):
        """Lambda в Copy URL захватывает правильный full_url (не последний в цикле)."""
        import mnemostroma.tools.tray_pyqt as tray_mod

        routes = {
            "/mcp":      {"auth": ["none"],   "client": "perplexity"},
            "/mcp/grok": {"auth": ["bearer"], "client": "grok"},
        }
        stub = self._make_stub(
            monkeypatch,
            url="https://mnemo-abc.serveo.net",
            token="tok123",
            routes=routes,
        )

        copied_urls = []
        monkeypatch.setattr(tray_mod, "_copy", lambda v: copied_urls.append(v))

        tray_mod.DaemonTrayApp._populate_tunnel_submenu(stub)

        for action in stub._tunnel_submenu.actions():
            submenu = action.menu()
            if submenu is None:
                continue
            for sub_action in submenu.actions():
                if "Copy URL" in sub_action.text():
                    sub_action.trigger()

        assert len(copied_urls) == 2, f"Ожидалось 2 URL, получено: {copied_urls}"
        assert "https://mnemo-abc.serveo.net/mcp" in copied_urls
        assert "https://mnemo-abc.serveo.net/mcp/grok" in copied_urls
