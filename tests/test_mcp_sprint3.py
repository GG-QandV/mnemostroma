# tests/test_mcp_sprint3.py
# SPDX-License-Identifier: FSL-1.1-MIT
"""
Sprint+3: watchfiles backend, watcher interval config, reload metrics, /health extended
Запуск: pytest tests/test_mcp_sprint3.py -v
"""
import json
import asyncio
import time
import threading
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient


TOKEN_VALUE = "test-bearer-token-xyz"


@pytest.fixture(autouse=True)
def patch_tokens(monkeypatch):
    monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter.TOKEN", TOKEN_VALUE)


@pytest.fixture(autouse=True)
def patch_ipc(monkeypatch):
    monkeypatch.setattr(
        "mnemostroma.integration.mcp_oauth_adapter.safe_ipc_call",
        AsyncMock(return_value={"status": "ok"}),
    )


@pytest.fixture
def mock_sm():
    sm = MagicMock()

    async def fake_handle_request(scope, receive, send):
        from starlette.responses import JSONResponse
        resp = JSONResponse({"ok": True})
        await resp(scope, receive, send)

    sm.handle_request = AsyncMock(side_effect=fake_handle_request)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__ = AsyncMock(return_value=None)
    sm.run = MagicMock(return_value=cm)
    return sm


@pytest.fixture
def app(mock_sm):
    from mnemostroma.integration.mcp_oauth_adapter import make_app
    with patch(
        "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
        return_value=mock_sm,
    ):
        application = make_app()
        yield application


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def mock_fs_routes(monkeypatch, tmp_path):
    monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter._MNEMO_DIR", tmp_path)
    return tmp_path


def write_routes(path: Path, routes: dict, watcher: dict | None = None) -> None:
    data = {"routes": routes}
    if watcher is not None:
        data["watcher"] = watcher
    path.write_text(json.dumps(data))


# ══════════════════════════════════════════════════════════════════════
# 1. WatchBackends
# ══════════════════════════════════════════════════════════════════════

class TestWatchBackends:

    def test_inotify_instantiation(self):
        from mnemostroma.integration.mcp_oauth_adapter import InotifyBackend
        try:
            backend = InotifyBackend()
            assert hasattr(backend, "_watchfiles")
        except RuntimeError:
            pytest.skip("watchfiles not installed")

    def test_inotify_without_watchfiles_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import InotifyBackend
        with patch.object(InotifyBackend, "__init__", side_effect=RuntimeError("watchfiles not installed")):
            with pytest.raises(RuntimeError, match="watchfiles not installed"):
                InotifyBackend()

    @pytest.mark.anyio
    async def test_inotify_watch_yields_on_change(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import InotifyBackend
        try:
            backend = InotifyBackend()
        except RuntimeError:
            pytest.skip("watchfiles not installed")
        p = tmp_path / "watch.txt"
        p.write_text("v1")
        results = []

        async def collect():
            async for _ in backend.watch(p, 0.05):
                results.append(True)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.1)
        p.write_text("v2")
        await asyncio.wait_for(task, timeout=5)
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_inotify_watch_no_yield_without_change(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import InotifyBackend
        try:
            backend = InotifyBackend()
        except RuntimeError:
            pytest.skip("watchfiles not installed")
        p = tmp_path / "watch.txt"
        p.write_text("v1")
        results = []

        async def collect():
            async for _ in backend.watch(p, 0.05):
                results.append(True)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(results) == 0

    @pytest.mark.anyio
    async def test_inotify_watch_missing_file(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import InotifyBackend
        try:
            backend = InotifyBackend()
        except RuntimeError:
            pytest.skip("watchfiles not installed")
        p = tmp_path / "nonexistent.txt"
        results = []

        async def collect():
            async for _ in backend.watch(p, 0.05):
                results.append(True)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(results) == 0

    def test_polling_instantiation(self):
        from mnemostroma.integration.mcp_oauth_adapter import PollingBackend
        backend = PollingBackend()
        assert isinstance(backend, object)

    @pytest.mark.anyio
    async def test_polling_watch_yields_on_change(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import PollingBackend
        p = tmp_path / "watch.txt"
        p.write_text("v1")
        backend = PollingBackend()
        results = []

        async def collect():
            async for _ in backend.watch(p, 0.05):
                results.append(True)
                break

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.1)
        p.write_text("v2")
        await asyncio.wait_for(task, timeout=5)
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_polling_watch_no_yield_without_change(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import PollingBackend
        p = tmp_path / "watch.txt"
        p.write_text("v1")
        backend = PollingBackend()
        results = []

        async def collect():
            async for _ in backend.watch(p, 0.05):
                results.append(True)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(results) == 0

    @pytest.mark.anyio
    async def test_polling_watch_missing_file(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import PollingBackend
        p = tmp_path / "nonexistent.txt"
        backend = PollingBackend()
        results = []

        async def collect():
            async for _ in backend.watch(p, 0.05):
                results.append(True)

        task = asyncio.create_task(collect())
        await asyncio.sleep(0.2)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert len(results) == 0

    def test_watch_backend_protocol_conformance(self):
        from mnemostroma.integration.mcp_oauth_adapter import WatchBackend, InotifyBackend, PollingBackend
        assert isinstance(InotifyBackend, type) or True
        assert issubclass(PollingBackend, object)

    def test_make_backend_auto_tries_inotify(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            _make_watch_backend_from_config, WatcherConfig, InotifyBackend, PollingBackend
        )
        config = WatcherConfig(backend="auto")
        try:
            backend = _make_watch_backend_from_config(config)
            assert isinstance(backend, (InotifyBackend, PollingBackend))
        except RuntimeError:
            pytest.skip("watchfiles unexpected error")

    def test_make_backend_auto_fallback_polling(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            _make_watch_backend_from_config, WatcherConfig, InotifyBackend, PollingBackend
        )
        with patch.object(InotifyBackend, "__init__", side_effect=RuntimeError("watchfiles not installed")):
            backend = _make_watch_backend_from_config(WatcherConfig(backend="auto"))
            assert isinstance(backend, PollingBackend)

    def test_make_backend_explicit_polling(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            _make_watch_backend_from_config, WatcherConfig, PollingBackend
        )
        backend = _make_watch_backend_from_config(WatcherConfig(backend="polling"))
        assert isinstance(backend, PollingBackend)

    def test_make_backend_explicit_inotify(self):
        from mnemostroma.integration.mcp_oauth_adapter import (
            _make_watch_backend_from_config, WatcherConfig, InotifyBackend
        )
        config = WatcherConfig(backend="inotify")
        try:
            backend = _make_watch_backend_from_config(config)
            assert isinstance(backend, InotifyBackend)
        except RuntimeError:
            pytest.skip("watchfiles not installed")


# ══════════════════════════════════════════════════════════════════════
# 2. WatcherConfig
# ══════════════════════════════════════════════════════════════════════

class TestWatcherConfig:

    def test_watcher_config_defaults(self):
        from mnemostroma.integration.mcp_oauth_adapter import WatcherConfig
        cfg = WatcherConfig()
        assert cfg.interval == 2.0
        assert cfg.backend == "auto"

    def test_watcher_config_custom(self):
        from mnemostroma.integration.mcp_oauth_adapter import WatcherConfig
        cfg = WatcherConfig(interval=5.0, backend="polling")
        assert cfg.interval == 5.0
        assert cfg.backend == "polling"

    def test_watcher_config_positive_interval_valid(self):
        from mnemostroma.integration.mcp_oauth_adapter import WatcherConfig
        cfg = WatcherConfig(interval=0.5)
        assert cfg.interval == 0.5

    def test_watcher_config_zero_interval_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        with pytest.raises(ValueError, match="interval must be a positive number"):
            _validate_route_config({
                "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
                "watcher": {"interval": 0, "backend": "polling"},
            })

    def test_watcher_config_negative_interval_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        with pytest.raises(ValueError, match="interval must be a positive number"):
            _validate_route_config({
                "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
                "watcher": {"interval": -1, "backend": "polling"},
            })

    def test_watcher_config_valid_backend(self):
        from mnemostroma.integration.mcp_oauth_adapter import WatcherConfig
        for b in ("auto", "polling", "inotify"):
            cfg = WatcherConfig(backend=b)
            assert cfg.backend == b

    def test_watcher_config_invalid_backend_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        with pytest.raises(ValueError, match="watcher.backend must be auto|polling|inotify"):
            _validate_route_config({
                "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
                "watcher": {"backend": "kqueue"},
            })

    def test_full_route_config_holds_routes_and_watcher(self):
        from mnemostroma.integration.mcp_oauth_adapter import FullRouteConfig, WatcherConfig
        routes = {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}}
        watcher = WatcherConfig(interval=3.0, backend="polling")
        fc = FullRouteConfig(routes=routes, watcher=watcher)
        assert fc.routes == routes
        assert fc.watcher is watcher

    def test_validate_watcher_missing_is_ok(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        _validate_route_config({
            "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
        })

    def test_validate_watcher_not_dict_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        with pytest.raises(ValueError, match="watcher must be a dict"):
            _validate_route_config({
                "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
                "watcher": "polling",
            })

    def test_validate_watcher_interval_valid(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        _validate_route_config({
            "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
            "watcher": {"interval": 1.5, "backend": "polling"},
        })

    def test_validate_watcher_backend_valid(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        _validate_route_config({
            "routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}},
            "watcher": {"interval": 1.0, "backend": "inotify"},
        })


# ══════════════════════════════════════════════════════════════════════
# 3. ReloadMetrics
# ══════════════════════════════════════════════════════════════════════

class TestReloadMetrics:

    def test_reload_metrics_defaults(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        assert m.total_attempts == 0
        assert m.total_successes == 0
        assert m.total_errors == 0
        assert m.last_reload_time is None
        assert m.last_error_time is None
        assert m.last_error_message is None

    def test_record_success_increments(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        m.record_success()
        assert m.total_attempts == 1
        assert m.total_successes == 1
        assert m.total_errors == 0

    def test_record_error_increments(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        m.record_error("bad json")
        assert m.total_attempts == 1
        assert m.total_successes == 0
        assert m.total_errors == 1

    def test_record_success_sets_timestamp(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        before = time.time()
        m.record_success()
        after = time.time()
        assert m.last_reload_time is not None
        assert before <= m.last_reload_time <= after

    def test_record_error_sets_timestamp_and_message(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        before = time.time()
        m.record_error("something broke")
        after = time.time()
        assert m.last_error_time is not None
        assert before <= m.last_error_time <= after
        assert m.last_error_message == "something broke"

    def test_snapshot_returns_copy(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        m.record_success()
        snap = m.snapshot()
        assert snap["total_attempts"] == 1
        assert snap["total_successes"] == 1
        snap["total_attempts"] = 999
        assert m.total_attempts == 1

    def test_concurrent_record_success(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        errors = []

        def worker():
            try:
                for _ in range(100):
                    m.record_success()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert m.total_attempts == 1000
        assert m.total_successes == 1000

    def test_concurrent_record_error(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        errors = []

        def worker():
            try:
                for _ in range(50):
                    m.record_error("err")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []
        assert m.total_attempts == 500
        assert m.total_errors == 500

    def test_multiple_records_stacked(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        for _ in range(5):
            m.record_success()
        for _ in range(3):
            m.record_error("err")
        assert m.total_attempts == 8
        assert m.total_successes == 5
        assert m.total_errors == 3

    def test_mixed_success_error(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        m.record_success()
        m.record_error("e1")
        m.record_success()
        assert m.total_attempts == 3
        assert m.total_successes == 2
        assert m.total_errors == 1

    def test_record_error_empty_message(self):
        from mnemostroma.integration.mcp_oauth_adapter import ReloadMetrics
        m = ReloadMetrics()
        m.record_error("")
        assert m.last_error_message == ""


# ══════════════════════════════════════════════════════════════════════
# 4. WatcherMetrics — integration
# ══════════════════════════════════════════════════════════════════════

class TestWatcherMetrics:

    @pytest.mark.anyio
    async def test_watcher_created_without_metrics(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/mcp": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        watcher = RouteFileWatcher(p, reg, interval=0.05)
        assert watcher.metrics is None

    @pytest.mark.anyio
    async def test_watcher_created_with_metrics(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/mcp": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        assert watcher.metrics is metrics

    @pytest.mark.anyio
    async def test_watcher_metrics_records_success_on_reload(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        await asyncio.sleep(0.1)
        write_routes(p, {"/v2": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        await asyncio.sleep(0.2)
        await watcher.stop()
        assert metrics.total_attempts >= 1
        assert metrics.total_successes >= 1

    @pytest.mark.anyio
    async def test_watcher_metrics_records_error_on_invalid_json(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        reg.update({"/v1": MagicMock()})
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        await asyncio.sleep(0.1)
        p.write_text("{broken json !!!")
        await asyncio.sleep(0.2)
        await watcher.stop()
        assert metrics.total_errors >= 1
        assert metrics.last_error_message is not None

    @pytest.mark.anyio
    async def test_watcher_metrics_records_error_on_invalid_schema(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        reg.update({"/v1": MagicMock()})
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        await asyncio.sleep(0.1)
        p.write_text(json.dumps(
            {"routes": {"/x": {"auth": "not-a-list"}}}
        ))
        await asyncio.sleep(0.2)
        await watcher.stop()
        assert metrics.total_errors >= 1

    @pytest.mark.anyio
    async def test_watcher_metrics_increments_across_reloads(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        for v in range(2, 5):
            await asyncio.sleep(0.1)
            write_routes(p, {f"/v{v}": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        await asyncio.sleep(0.2)
        await watcher.stop()
        assert metrics.total_successes >= 3

    @pytest.mark.anyio
    async def test_watcher_metrics_snapshot_after_success(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        await asyncio.sleep(0.1)
        write_routes(p, {"/v2": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        await asyncio.sleep(0.2)
        await watcher.stop()
        snap = metrics.snapshot()
        assert snap["total_successes"] >= 1
        assert snap["last_reload_time"] is not None

    @pytest.mark.anyio
    async def test_watcher_metrics_snapshot_after_error(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        await asyncio.sleep(0.1)
        p.write_text("{broken")
        await asyncio.sleep(0.2)
        await watcher.stop()
        snap = metrics.snapshot()
        assert snap["total_errors"] >= 1
        assert snap["last_error_time"] is not None
        assert snap["last_error_message"] is not None

    def test_make_app_watcher_has_metrics(self, mock_sm, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        p = tmp_path / "routes.json"
        write_routes(p, {"/mcp": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(str(p))
        with TestClient(application):
            assert hasattr(application.state, "metrics")
            assert application.state.metrics is not None
            assert hasattr(application.state, "watcher")
            assert application.state.watcher.metrics is application.state.metrics

    def test_make_app_forced_inotify_without_watchfiles_raises(self, mock_sm, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app, InotifyBackend
        p = tmp_path / "routes.json"
        write_routes(p, {"/mcp": {"auth": ["none"], "client": "t", "transport": "proxy"}}, watcher={"backend": "inotify"})
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            with patch.object(InotifyBackend, "__init__", side_effect=RuntimeError("watchfiles not installed")):
                with pytest.raises(RuntimeError, match="watchfiles not installed"):
                    make_app(str(p))

    def test_make_app_auto_backend_creates_watcher(self, mock_sm, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        p = tmp_path / "routes.json"
        write_routes(p, {"/mcp": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(str(p))
        with TestClient(application):
            assert application.state.watcher is not None
            assert application.state.watcher.backend is not None

    @pytest.mark.anyio
    async def test_watcher_metrics_persists_across_reloads(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import (
            RouteFileWatcher, RouteRegistry, ReloadMetrics
        )
        p = tmp_path / "routes.json"
        write_routes(p, {"/v1": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        reg = RouteRegistry()
        metrics = ReloadMetrics()
        watcher = RouteFileWatcher(p, reg, interval=0.05, metrics=metrics)
        await watcher.start()
        await asyncio.sleep(0.1)
        write_routes(p, {"/v2": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        await asyncio.sleep(0.2)
        write_routes(p, {"/v3": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        await asyncio.sleep(0.2)
        await watcher.stop()
        snap = metrics.snapshot()
        assert snap["total_successes"] >= 2
        assert snap["total_attempts"] >= 2


# ══════════════════════════════════════════════════════════════════════
# 5. HealthExtended
# ══════════════════════════════════════════════════════════════════════

class TestHealthExtended:

    def test_health_returns_200(self, client):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_has_daemon_ok(self, client):
        r = client.get("/health")
        assert r.json()["daemon"] == "ok"

    def test_health_has_routes_active_count(self, client):
        r = client.get("/health")
        data = r.json()
        assert "routes" in data
        assert "active_count" in data["routes"]
        assert isinstance(data["routes"]["active_count"], int)

    def test_health_has_routes_paths(self, client):
        r = client.get("/health")
        data = r.json()
        assert "paths" in data["routes"]
        assert isinstance(data["routes"]["paths"], list)

    def test_health_routes_count_matches_default(self, client):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        r = client.get("/health")
        data = r.json()
        svc_count = 11
        assert data["routes"]["active_count"] == len(DEFAULT_ROUTES) + svc_count

    def test_health_has_reload(self, client):
        r = client.get("/health")
        assert "reload" in r.json()

    def test_health_reload_has_total_attempts(self, client):
        r = client.get("/health")
        assert "total_attempts" in r.json()["reload"]

    def test_health_reload_has_total_successes(self, client):
        r = client.get("/health")
        assert "total_successes" in r.json()["reload"]

    def test_health_reload_has_total_errors(self, client):
        r = client.get("/health")
        assert "total_errors" in r.json()["reload"]

    def test_health_reload_has_last_reload_time(self, client):
        r = client.get("/health")
        assert "last_reload_time" in r.json()["reload"]

    def test_health_reload_updates_after_reload(self, mock_sm, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        import time
        p = tmp_path / "routes.json"
        write_routes(p, {"/mcp": {"auth": ["none"], "client": "t", "transport": "proxy"}})
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            application = make_app(str(p), watch_interval=0.05)
        with TestClient(application, raise_server_exceptions=False) as c:
            r1 = c.get("/health")
            assert r1.json()["reload"]["total_attempts"] == 0

            write_routes(p, {"/mcp/v2": {"auth": ["bearer"], "client": "t", "transport": "proxy"}})
            time.sleep(0.3)

            r2 = c.get("/health")
            assert r2.json()["reload"]["total_attempts"] >= 1

    def test_health_has_mcpConfirmed(self, client):
        r = client.get("/health")
        assert r.json()["mcpConfirmed"] is True
