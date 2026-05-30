# tests/test_mcp_hot_reload.py
# SPDX-License-Identifier: FSL-1.1-MIT
"""
Sprint+2: hot reload routes.json без рестарта адаптера
Запуск: pytest tests/test_mcp_hot_reload.py -v
"""
import json
import asyncio
import pytest
import httpx
import respx
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, call
from starlette.testclient import TestClient


TOKEN_VALUE = "test-bearer-token-xyz"


class MockResponse:
    def __init__(self, status_code, content, headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    async def aiter_bytes(self):
        yield self.content

    def __aenter__(self):
        return self

    def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture(autouse=True)
def patch_tokens(monkeypatch):
    monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter.TOKEN", TOKEN_VALUE)

@pytest.fixture(autouse=True)
def patch_ipc(monkeypatch):
    monkeypatch.setattr(
        "mnemostroma.integration.mcp_oauth_adapter.safe_ipc_call",
        AsyncMock(return_value={"status": "ok"}),
    )

@pytest.fixture(autouse=True)
def mock_httpx(monkeypatch):
    """Предотвращаем реальные HTTP запросы — мокаем AsyncClient."""
    async def mock_request(self, method, url, **kwargs):
        return MockResponse(200, b'{"ok": true}', {"content-type": "application/json"})

    class MockStreamContext:
        def __init__(self, method, url, **kwargs):
            self.url = url

        async def __aenter__(self):
            return MockResponse(200, b"data: ping\n\n", {"content-type": "text/event-stream"})

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)
    monkeypatch.setattr(httpx.AsyncClient, "stream", MockStreamContext)

@pytest.fixture
def mock_sm():
    sm = MagicMock()
    sm.handle_request = AsyncMock()
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__  = AsyncMock(return_value=None)
    sm.run = MagicMock(return_value=cm)
    return sm

@pytest.fixture
def routes_file(tmp_path) -> Path:
    return tmp_path / "routes.json"

@pytest.fixture
def bearer_headers():
    return {"Authorization": f"Bearer {TOKEN_VALUE}"}

def write_routes(path: Path, routes: dict) -> None:
    path.write_text(json.dumps({"routes": routes}))


# ══════════════════════════════════════════════════════════════════════
# 1. RouteRegistry
# ══════════════════════════════════════════════════════════════════════

class TestRouteRegistry:

    def _make_entry(self, auth=None):
        from mnemostroma.integration.mcp_oauth_adapter import RouteEntry, AuthMode
        return RouteEntry(
            auth_modes=auth or [AuthMode.NONE],
            handler=AsyncMock(),
            methods=["GET", "POST"],
        )

    def test_exact_match(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        entry = self._make_entry()
        reg.update({"/mcp": entry})
        assert reg.match("/mcp") is entry

    def test_no_match_returns_none(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        reg.update({"/mcp": self._make_entry()})
        assert reg.match("/unknown") is None

    def test_wildcard_prefix_match(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        entry = self._make_entry()
        reg.update({"/context-manager/{rest:path}": entry})
        assert reg.match("/context-manager/health") is entry
        assert reg.match("/context-manager/a/b/c") is entry

    def test_exact_takes_priority_over_wildcard(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        exact_entry   = self._make_entry()
        wildcard_entry = self._make_entry()
        reg.update({
            "/context-manager/health": exact_entry,
            "/context-manager/{rest:path}": wildcard_entry,
        })
        assert reg.match("/context-manager/health") is exact_entry

    def test_update_is_atomic(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        reg.update({"/old": self._make_entry()})
        new_entry = self._make_entry()
        reg.update({"/new": new_entry})
        assert reg.match("/old") is None
        assert reg.match("/new") is new_entry

    def test_thread_safe_concurrent_reads(self):
        import threading
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        reg.update({f"/route{i}": self._make_entry() for i in range(50)})
        errors = []

        def read():
            try:
                for _ in range(100):
                    reg.match("/route25")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=read) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []

    def test_thread_safe_write_during_read(self):
        import threading
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        reg.update({"/mcp": self._make_entry()})
        errors = []
        stop = threading.Event()

        def reader():
            while not stop.is_set():
                try:
                    reg.match("/mcp")
                except Exception as e:
                    errors.append(e)

        def writer():
            for i in range(20):
                reg.update({f"/mcp{i}": self._make_entry()})

        r = threading.Thread(target=reader)
        w = threading.Thread(target=writer)
        r.start()
        w.start()
        w.join()
        stop.set()
        r.join()
        assert errors == []

    def test_empty_registry_match_returns_none(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        assert reg.match("/anything") is None

    def test_current_returns_snapshot(self):
        from mnemostroma.integration.mcp_oauth_adapter import RouteRegistry
        reg = RouteRegistry()
        entry = self._make_entry()
        reg.update({"/mcp": entry})
        snapshot = reg.current
        snapshot["/injected"] = self._make_entry()
        assert "/injected" not in reg.current


# ══════════════════════════════════════════════════════════════════════
# 2. DynamicRouter
# ══════════════════════════════════════════════════════════════════════

class TestDynamicRouter:

    def _registry_with(self, path, auth_modes, handler, methods):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteRegistry, RouteEntry
        )
        reg = RouteRegistry()
        reg.update({path: RouteEntry(
            auth_modes=auth_modes,
            handler=handler,
            methods=methods,
        )})
        return reg

    @pytest.mark.anyio
    async def test_known_route_dispatched(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            DynamicRouter, AuthMode
        )
        handler = AsyncMock()
        reg = self._registry_with("/mcp", [AuthMode.NONE], handler, ["GET"])
        router = DynamicRouter(reg)

        scope = {"type": "http", "path": "/mcp", "method": "GET",
                 "headers": [], "query_string": b""}
        await router(scope, AsyncMock(), AsyncMock())
        handler.assert_called_once()

    @pytest.mark.anyio
    async def test_unknown_route_returns_404(self):
        from mnemostroma.integration.mcp_oauth_adapter import DynamicRouter, RouteRegistry
        router = DynamicRouter(RouteRegistry())
        sent = []
        async def send(msg):
            sent.append(msg)
        scope = {"type": "http", "path": "/unknown", "method": "GET",
                 "headers": [], "query_string": b""}
        await router(scope, AsyncMock(), send)
        status = next(m["status"] for m in sent if m.get("type") == "http.response.start")
        assert status == 404

    @pytest.mark.anyio
    async def test_wrong_method_returns_405(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            DynamicRouter, AuthMode
        )
        handler = AsyncMock()
        reg = self._registry_with("/mcp", [AuthMode.NONE], handler, ["GET"])
        router = DynamicRouter(reg)
        sent = []
        async def send(msg):
            sent.append(msg)
        scope = {"type": "http", "path": "/mcp", "method": "DELETE",
                 "headers": [], "query_string": b""}
        await router(scope, AsyncMock(), send)
        status = next(m["status"] for m in sent if m.get("type") == "http.response.start")
        assert status == 405

    @pytest.mark.anyio
    async def test_auth_applied_per_route(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            DynamicRouter, AuthMode
        )
        handler = AsyncMock()
        reg = self._registry_with("/sse", [AuthMode.BEARER], handler, ["GET"])
        router = DynamicRouter(reg)
        sent = []
        async def send(msg):
            sent.append(msg)
        scope = {"type": "http", "path": "/sse", "method": "GET",
                 "headers": [], "query_string": b""}
        await router(scope, AsyncMock(), send)
        status = next(m["status"] for m in sent if m.get("type") == "http.response.start")
        assert status == 401
        handler.assert_not_called()

    @pytest.mark.anyio
    async def test_non_http_scope_ignored(self):
        from mnemostroma.integration.mcp_oauth_adapter import DynamicRouter, RouteRegistry
        router = DynamicRouter(RouteRegistry())
        await router({"type": "lifespan"}, AsyncMock(), AsyncMock())

    @pytest.mark.anyio
    async def test_route_updated_mid_flight(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            DynamicRouter, RouteRegistry, RouteEntry, AuthMode
        )
        reg = RouteRegistry()
        old_handler = AsyncMock()
        new_handler = AsyncMock()

        reg.update({"/mcp": RouteEntry([AuthMode.NONE], old_handler, ["GET"])})
        router = DynamicRouter(reg)

        scope = {"type": "http", "path": "/mcp", "method": "GET",
                 "headers": [], "query_string": b""}

        await router(scope, AsyncMock(), AsyncMock())
        old_handler.assert_called_once()

        reg.update({"/mcp": RouteEntry([AuthMode.NONE], new_handler, ["GET"])})

        await router(scope, AsyncMock(), AsyncMock())
        new_handler.assert_called_once()
        old_handler.assert_called_once()


# ══════════════════════════════════════════════════════════════════════
# 3. RouteFileWatcher
# ══════════════════════════════════════════════════════════════════════

class TestRouteFileWatcher:

    @pytest.mark.anyio
    async def test_reload_on_mtime_change(self, routes_file, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry
        )
        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        reg = RouteRegistry()
        watcher = RouteFileWatcher(routes_file, reg, interval=0.05)
        await watcher.start()
        await asyncio.sleep(0.1)

        write_routes(routes_file, {
            "/mcp/v2": {"auth": ["bearer"], "transport": "streamable-http", "client": "new"}
        })
        await asyncio.sleep(0.2)

        await watcher.stop()
        assert reg.match("/mcp/v2") is not None

    @pytest.mark.anyio
    async def test_no_reload_without_change(self, routes_file, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry
        )
        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        reg = RouteRegistry()
        reload_count = 0
        original_reload = RouteFileWatcher._reload

        async def counting_reload(self_inner):
            nonlocal reload_count
            reload_count += 1
            await original_reload(self_inner)

        watcher = RouteFileWatcher(routes_file, reg, interval=0.05)
        watcher._reload = counting_reload.__get__(watcher)
        await watcher.start()
        await asyncio.sleep(0.3)
        await watcher.stop()
        assert reload_count == 0

    @pytest.mark.anyio
    async def test_invalid_json_keeps_current_routes(self, routes_file, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, RouteEntry, AuthMode
        )
        old_entry = RouteEntry([AuthMode.NONE], AsyncMock(), ["GET"])
        reg = RouteRegistry()
        reg.update({"/mcp": old_entry})

        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        watcher = RouteFileWatcher(routes_file, reg, interval=0.05)
        await watcher.start()
        await asyncio.sleep(0.1)

        routes_file.write_text("{broken json !!!")
        await asyncio.sleep(0.2)

        await watcher.stop()
        assert reg.match("/mcp") is not None

    @pytest.mark.anyio
    async def test_invalid_schema_keeps_current_routes(self, routes_file):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, RouteEntry, AuthMode
        )
        old_entry = RouteEntry([AuthMode.NONE], AsyncMock(), ["GET"])
        reg = RouteRegistry()
        reg.update({"/mcp": old_entry})

        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "x"}
        })
        watcher = RouteFileWatcher(routes_file, reg, interval=0.05)
        await watcher.start()
        await asyncio.sleep(0.1)

        routes_file.write_text(json.dumps(
            {"routes": {"/mcp": {"auth": "not-a-list"}}}
        ))
        await asyncio.sleep(0.2)
        await watcher.stop()
        assert reg.match("/mcp") is not None

    @pytest.mark.anyio
    async def test_file_deleted_keeps_current_routes(self, routes_file):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, RouteEntry, AuthMode
        )
        old_entry = RouteEntry([AuthMode.NONE], AsyncMock(), ["GET"])
        reg = RouteRegistry()
        reg.update({"/mcp": old_entry})

        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "x"}
        })
        watcher = RouteFileWatcher(routes_file, reg, interval=0.05)
        await watcher.start()
        await asyncio.sleep(0.1)

        routes_file.unlink()
        await asyncio.sleep(0.2)
        await watcher.stop()
        assert reg.match("/mcp") is not None, "Deleted file keeps current routes"

    @pytest.mark.anyio
    async def test_watcher_stops_cleanly(self, routes_file):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry
        )
        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "x"}
        })
        reg = RouteRegistry()
        watcher = RouteFileWatcher(routes_file, reg, interval=0.1)
        await watcher.start()
        assert watcher._task is not None
        await watcher.stop()
        assert watcher._task.cancelled() or watcher._task.done()

    @pytest.mark.anyio
    async def test_multiple_sequential_reloads(self, routes_file):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry
        )
        reg = RouteRegistry()
        write_routes(routes_file, {
            "/v1": {"auth": ["none"], "transport": "streamable-http", "client": "x"}
        })
        watcher = RouteFileWatcher(routes_file, reg, interval=0.05)
        await watcher.start()
        await asyncio.sleep(0.1)

        for version in range(2, 5):
            write_routes(routes_file, {
                f"/v{version}": {"auth": ["none"], "transport": "streamable-http", "client": "x"}
            })
            await asyncio.sleep(0.15)

        await watcher.stop()
        assert reg.match("/v4") is not None
        assert reg.match("/v1") is None


# ══════════════════════════════════════════════════════════════════════
# 4. Интеграция: lifespan запускает watcher
# ══════════════════════════════════════════════════════════════════════

class TestLifespanWithWatcher:

    def test_watcher_starts_with_lifespan(self, mock_sm, routes_file):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(routes_config_path=routes_file, watch_interval=0.05)

        with TestClient(application) as c:
            assert application.state.watcher._task is not None
            assert not application.state.watcher._task.done()

    def test_watcher_stops_after_lifespan(self, mock_sm, routes_file):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(routes_config_path=routes_file, watch_interval=0.05)

        with TestClient(application):
            pass
        assert application.state.watcher._task.done()

    def test_initial_routes_active_after_startup(self, mock_sm, routes_file, bearer_headers):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"},
            "/sse": {"auth": ["bearer"], "transport": "sse", "client": "claude"},
        })
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(routes_config_path=routes_file, watch_interval=0.05)
        with TestClient(application, raise_server_exceptions=False) as c:
            assert c.get("/mcp").status_code != 401
            assert c.get("/sse").status_code == 401
            assert c.get("/sse", headers=bearer_headers).status_code != 401

    def test_hot_reload_changes_auth_live(self, mock_sm, routes_file, bearer_headers):
        import time
        from mnemostroma.integration.mcp_oauth_adapter import make_app

        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(routes_config_path=routes_file, watch_interval=0.05)

        with TestClient(application, raise_server_exceptions=False) as c:
            assert c.get("/mcp").status_code != 401

            write_routes(routes_file, {
                "/mcp": {"auth": ["bearer"], "transport": "streamable-http", "client": "perplexity"}
            })
            time.sleep(0.3)

            assert c.get("/mcp").status_code == 401
            assert c.get("/mcp", headers=bearer_headers).status_code != 401

    def test_bad_reload_keeps_old_routes_live(self, mock_sm, routes_file):
        import time
        from mnemostroma.integration.mcp_oauth_adapter import make_app

        write_routes(routes_file, {
            "/mcp": {"auth": ["none"], "transport": "streamable-http", "client": "perplexity"}
        })
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(routes_config_path=routes_file, watch_interval=0.05)

        with TestClient(application, raise_server_exceptions=False) as c:
            assert c.get("/mcp").status_code != 401

            routes_file.write_text("{bad!!!")
            time.sleep(0.3)

            assert c.get("/mcp").status_code != 401


# ══════════════════════════════════════════════════════════════════════
# 5. _config_to_entries
# ══════════════════════════════════════════════════════════════════════

class TestConfigToEntries:

    def test_all_transports_mapped(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            _config_to_entries, _HANDLER_MAP
        )
        cfg = {
            path: {"auth": ["none"], "transport": transport, "client": "x"}
            for path, transport in [
                ("/mcp",           "streamable-http"),
                ("/sse",           "sse"),
                ("/messages/",     "sse-messages"),
                ("/cm/{rest:path}","proxy"),
            ]
        }
        entries = _config_to_entries(cfg)
        assert entries["/mcp"].handler     is _HANDLER_MAP["streamable-http"]
        assert entries["/sse"].handler     is _HANDLER_MAP["sse"]
        assert entries["/messages/"].handler is _HANDLER_MAP["sse-messages"]
        assert entries["/cm/{rest:path}"].handler is _HANDLER_MAP["proxy"]

    def test_unknown_transport_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _config_to_entries
        with pytest.raises(ValueError, match="Unknown transport"):
            _config_to_entries({
                "/mcp": {"auth": ["none"], "transport": "grpc", "client": "x"}
            })

    def test_auth_modes_correctly_parsed(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            _config_to_entries, AuthMode
        )
        entries = _config_to_entries({
            "/sse": {"auth": ["oauth", "bearer"], "transport": "sse", "client": "claude"}
        })
        assert entries["/sse"].auth_modes == [AuthMode.OAUTH, AuthMode.BEARER]

    def test_methods_match_transport(self):
        from mnemostroma.integration.mcp_oauth_adapter import _config_to_entries
        entries = _config_to_entries({
            "/mcp":       {"auth": ["none"],    "transport": "streamable-http", "client": "x"},
            "/sse":       {"auth": ["bearer"],  "transport": "sse",             "client": "x"},
            "/messages/": {"auth": ["bearer"],  "transport": "sse-messages",    "client": "x"},
        })
        assert "DELETE" in entries["/mcp"].methods
        assert "GET"    in entries["/sse"].methods
        assert "DELETE" not in entries["/sse"].methods
        assert entries["/messages/"].methods == ["POST"]
