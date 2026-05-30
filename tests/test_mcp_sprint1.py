# tests/test_mcp_sprint1.py
# SPDX-License-Identifier: FSL-1.1-MIT
"""Sprint+1: config-driven routing, /mcp-config response, proxy_to_cm coverage."""

import json
import httpx
import pytest
import respx
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
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
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def bearer_headers():
    return {"Authorization": f"Bearer {TOKEN_VALUE}"}


@pytest.fixture(autouse=True)
def mock_fs_routes(monkeypatch, tmp_path):
    """By default, no routes.json exists → DEFAULT_ROUTES used.
    Tests that need a custom file can write to tmp_path / routes.json."""
    monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter._MNEMO_DIR", tmp_path)
    return tmp_path


# ══════════════════════════════════════════════════════════════════════
# 1. LoadRouteConfig — validation, defaults, file loading
# ══════════════════════════════════════════════════════════════════════

class TestLoadRouteConfig:

    def test_default_routes_has_all_keys(self):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        expected = {"/mcp", "/sse", "/messages/", "/mcp/chatgpt",
                    "/mcp/grok", "/context-manager", "/context-manager/{rest:path}"}
        assert set(DEFAULT_ROUTES) == expected

    def test_default_routes_auth_is_list(self):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        for path, cfg in DEFAULT_ROUTES.items():
            assert isinstance(cfg["auth"], list), f"{path}.auth not a list"

    def test_default_routes_auth_modes_valid(self):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES, VALID_AUTH_MODES
        for path, cfg in DEFAULT_ROUTES.items():
            for mode in cfg["auth"]:
                assert mode in VALID_AUTH_MODES, f"{path} has invalid mode {mode}"

    def test_default_routes_all_have_transport(self):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        for path, cfg in DEFAULT_ROUTES.items():
            assert "transport" in cfg, f"{path} missing transport"

    def test_default_routes_all_have_client(self):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        for path, cfg in DEFAULT_ROUTES.items():
            assert "client" in cfg, f"{path} missing client"

    def test_validate_route_config_valid_passes(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        data = {"routes": {"/test": {"auth": ["none"], "client": "t", "transport": "proxy"}}}
        _validate_route_config(data)

    def test_validate_route_config_auth_not_list_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        data = {"routes": {"/test": {"auth": "bearer", "client": "t", "transport": "proxy"}}}
        with pytest.raises(ValueError, match="auth must be a list"):
            _validate_route_config(data)

    def test_validate_route_config_unknown_mode_raises(self):
        from mnemostroma.integration.mcp_oauth_adapter import _validate_route_config
        data = {"routes": {"/test": {"auth": ["magic"], "client": "t", "transport": "proxy"}}}
        with pytest.raises(ValueError, match="unknown modes"):
            _validate_route_config(data)

    def test_load_route_config_no_file_returns_defaults(self):
        from mnemostroma.integration.mcp_oauth_adapter import load_route_config, DEFAULT_ROUTES
        result = load_route_config(Path("/nonexistent/path/routes.json"))
        assert result.routes == DEFAULT_ROUTES

    def test_load_route_config_from_path(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import load_route_config
        config = {"routes": {"/custom": {"auth": ["none"], "client": "test", "transport": "proxy"}}}
        p = tmp_path / "my_routes.json"
        p.write_text(json.dumps(config))
        result = load_route_config(p)
        assert "/custom" in result.routes
        assert result.routes["/custom"]["auth"] == ["none"]

    def test_load_route_config_invalid_raises(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import load_route_config
        p = tmp_path / "bad.json"
        p.write_text(json.dumps({"routes": {"/x": {"auth": "nope"}}}))
        with pytest.raises(ValueError):
            load_route_config(p)

    def test_load_route_config_empty_routes(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import load_route_config
        p = tmp_path / "empty.json"
        p.write_text(json.dumps({"routes": {}}))
        result = load_route_config(p)
        assert result.routes == {}


# ══════════════════════════════════════════════════════════════════════
# 2. MakeAppWithConfig — dynamic app construction
# ══════════════════════════════════════════════════════════════════════

class TestMakeAppWithConfig:

    def test_make_app_uses_provided_config(self, mock_sm, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        config = {"routes": {"/custom": {"auth": ["none"], "client": "t", "transport": "streamable-http"}}}
        p = tmp_path / "routes.json"
        p.write_text(json.dumps(config))
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            app = make_app(str(p))
        with TestClient(app) as c:
            r = c.get("/custom")
            assert r.status_code != 404

    def test_make_app_no_path_uses_defaults(self, mock_sm):
        from mnemostroma.integration.mcp_oauth_adapter import make_app, DEFAULT_ROUTES
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            app = make_app()
        with TestClient(app) as c:
            for path in DEFAULT_ROUTES:
                methods = {"GET"}
                if path in ("/messages/",):
                    continue
                if path in ("/context-manager", "/context-manager/{rest:path}"):
                    continue
                r = c.request("GET", path)
                assert r.status_code != 404, f"{path} not found"

    def test_make_app_invalid_config_raises(self, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        p = tmp_path / "bad_routes.json"
        p.write_text(json.dumps({"routes": {"/x": {"auth": "not_a_list"}}}))
        with pytest.raises(ValueError):
            make_app(str(p))

    def test_make_app_service_routes_present(self, mock_sm):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            app = make_app()
        with TestClient(app) as c:
            for svc in ("/health", "/mcp-config", "/.well-known/oauth-authorization-server",
                        "/register", "/authorize", "/token"):
                r = c.get(svc)
                assert r.status_code != 404, f"{svc} not found"

    def test_make_app_transport_proxy_registered(self, mock_sm):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            app = make_app()
        with TestClient(app) as c:
            r = c.get("/context-manager/health", headers={"Authorization": f"Bearer {TOKEN_VALUE}"})
            assert r.status_code != 404

    def test_make_app_lifespan_sets_route_config(self, mock_sm):
        from mnemostroma.integration.mcp_oauth_adapter import make_app, DEFAULT_ROUTES
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            app = make_app()
        with TestClient(app) as c:
            assert app.state.route_config.routes == DEFAULT_ROUTES

    def test_make_app_with_custom_config_overrides_defaults(self, mock_sm, tmp_path):
        from mnemostroma.integration.mcp_oauth_adapter import make_app
        config = {"routes": {"/custom-only": {"auth": ["none"], "client": "t", "transport": "proxy"}}}
        p = tmp_path / "routes.json"
        p.write_text(json.dumps(config))
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter.StreamableHTTPSessionManager",
            return_value=mock_sm,
        ):
            app = make_app(str(p))
        with TestClient(app, raise_server_exceptions=False) as c:
            with respx.mock:
                respx.get("http://localhost:3847/custom-only").mock(
                    return_value=httpx.Response(200, json={"ok": True})
                )
                r = c.get("/custom-only")
            assert r.status_code != 404


# ══════════════════════════════════════════════════════════════════════
# 3. McpConfigHandler — full /mcp-config response
# ══════════════════════════════════════════════════════════════════════

class TestMcpConfigHandler:

    def test_mcp_config_returns_200(self, client):
        r = client.get("/mcp-config")
        assert r.status_code == 200

    def test_mcp_config_has_serveo_url(self, client):
        r = client.get("/mcp-config")
        data = r.json()
        assert "serveo_url" in data

    def test_mcp_config_has_routes_dict(self, client):
        r = client.get("/mcp-config")
        data = r.json()
        assert "routes" in data
        assert isinstance(data["routes"], dict)

    def test_mcp_config_routes_contain_all_defaults(self, client):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        r = client.get("/mcp-config")
        routes = r.json()["routes"]
        for path in DEFAULT_ROUTES:
            assert path in routes, f"{path} missing from /mcp-config"

    def test_mcp_config_route_has_url(self, client):
        r = client.get("/mcp-config")
        for path, cfg in r.json()["routes"].items():
            assert "url" in cfg, f"{path} missing url"

    def test_mcp_config_route_has_auth(self, client):
        r = client.get("/mcp-config")
        for path, cfg in r.json()["routes"].items():
            assert "auth" in cfg, f"{path} missing auth"
            assert isinstance(cfg["auth"], list)

    def test_mcp_config_route_has_client(self, client):
        r = client.get("/mcp-config")
        for path, cfg in r.json()["routes"].items():
            assert "client" in cfg, f"{path} missing client"

    def test_mcp_config_route_has_transport(self, client):
        r = client.get("/mcp-config")
        for path, cfg in r.json()["routes"].items():
            assert "transport" in cfg, f"{path} missing transport"

    def test_mcp_config_bearer_token_present_for_bearer_routes(self, client):
        from mnemostroma.integration.mcp_oauth_adapter import DEFAULT_ROUTES
        r = client.get("/mcp-config")
        routes = r.json()["routes"]
        tunnel_token = r.json().get("tunnel_token")
        for path, cfg_orig in DEFAULT_ROUTES.items():
            if "bearer" in cfg_orig["auth"]:
                assert "bearer_token" in routes[path], f"{path} missing bearer_token"

    def test_mcp_config_bearer_token_none_for_no_bearer(self, client):
        r = client.get("/mcp-config")
        routes = r.json()["routes"]
        assert routes["/mcp"]["bearer_token"] is None

    def test_mcp_config_has_daemon_status(self, client):
        r = client.get("/mcp-config")
        data = r.json()
        assert "daemon_status" in data
        assert data["daemon_status"] == "ok"

    def test_mcp_config_daemon_status_unreachable(self, client, monkeypatch):
        async def mock_fail(*args, **kwargs):
            raise ConnectionError("refused")
        monkeypatch.setattr(
            "mnemostroma.integration.mcp_oauth_adapter.safe_ipc_call",
            mock_fail,
        )
        r = client.get("/mcp-config")
        data = r.json()
        assert data["daemon_status"] == "unreachable"

    def test_mcp_config_serveo_url_read_from_file(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter._MNEMO_DIR", tmp_path)
        (tmp_path / "serveo_url").write_text("https://test.serveo.net")
        r = client.get("/mcp-config")
        data = r.json()
        assert data["serveo_url"] == "https://test.serveo.net"

    def test_mcp_config_serveo_url_none_when_missing(self, client):
        r = client.get("/mcp-config")
        assert r.json()["serveo_url"] is None

    def test_mcp_config_route_url_constructed(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter._MNEMO_DIR", tmp_path)
        (tmp_path / "serveo_url").write_text("https://test.serveo.net")
        r = client.get("/mcp-config")
        routes = r.json()["routes"]
        assert routes["/mcp"]["url"] == "https://test.serveo.net/mcp"
        assert routes["/sse"]["url"] == "https://test.serveo.net/sse"

    def test_mcp_config_tunnel_token_included(self, client, tmp_path, monkeypatch):
        monkeypatch.setattr("mnemostroma.integration.mcp_oauth_adapter._MNEMO_DIR", tmp_path)
        (tmp_path / "tunnel_token").write_text("tok-secret-42")
        r = client.get("/mcp-config")
        data = r.json()
        assert "tunnel_token" in data
        assert data["tunnel_token"] == "tok-secret-42"


# ══════════════════════════════════════════════════════════════════════
# 4. ProxyToCmAllMethods — coverage for all HTTP methods + errors
# ══════════════════════════════════════════════════════════════════════

class TestProxyToCmAllMethods:

    @respx.mock
    def test_proxy_get_passes_through(self, client, bearer_headers):
        respx.get("http://localhost:3847/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        r = client.get("/context-manager/health", headers=bearer_headers)
        assert r.status_code == 200

    @respx.mock
    def test_proxy_post_passes_through(self, client, bearer_headers):
        respx.post("http://localhost:3847/data").mock(
            return_value=httpx.Response(201, json={"created": True})
        )
        r = client.post("/context-manager/data", headers=bearer_headers, json={"key": "val"})
        assert r.status_code == 201

    @respx.mock
    def test_proxy_put_passes_through(self, client, bearer_headers):
        respx.put("http://localhost:3847/data/1").mock(
            return_value=httpx.Response(200, json={"updated": True})
        )
        r = client.put("/context-manager/data/1", headers=bearer_headers, json={"key": "val"})
        assert r.status_code == 200

    @respx.mock
    def test_proxy_patch_passes_through(self, client, bearer_headers):
        respx.patch("http://localhost:3847/data/1").mock(
            return_value=httpx.Response(200, json={"patched": True})
        )
        r = client.patch("/context-manager/data/1", headers=bearer_headers, json={"key": "val"})
        assert r.status_code == 200

    @respx.mock
    def test_proxy_delete_passes_through(self, client, bearer_headers):
        respx.delete("http://localhost:3847/data/1").mock(
            return_value=httpx.Response(204)
        )
        r = client.delete("/context-manager/data/1", headers=bearer_headers)
        assert r.status_code == 204

    @respx.mock
    def test_proxy_connect_error_returns_502(self, client, bearer_headers):
        respx.get("http://localhost:3847/health").mock(
            side_effect=httpx.ConnectError("refused")
        )
        r = client.get("/context-manager/health", headers=bearer_headers)
        assert r.status_code == 502
        assert r.json()["error"] == "bad_gateway"

    @respx.mock
    def test_proxy_timeout_returns_504(self, client, bearer_headers):
        respx.get("http://localhost:3847/health").mock(
            side_effect=httpx.TimeoutException("timed out")
        )
        r = client.get("/context-manager/health", headers=bearer_headers)
        assert r.status_code == 504
        assert r.json()["error"] == "gateway_timeout"

    @respx.mock
    def test_proxy_strips_authorization_header(self, client, bearer_headers):
        captured = {}

        async def capture(request):
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"ok": True})

        respx.get("http://localhost:3847/data").mock(side_effect=capture)
        client.get("/context-manager/data", headers=bearer_headers)
        headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
        assert "authorization" not in headers_lower

    def test_proxy_strips_host_header(self, client, bearer_headers):
        """Verify proxy strips Host from headers passed to httpx."""
        from mnemostroma.integration.mcp_oauth_adapter import CM_UPSTREAM
        captured = {}

        async def mock_request(self, method, url, **kwargs):
            captured["headers"] = kwargs.get("headers", {})
            return httpx.Response(200, json={"ok": True})

        with patch("httpx.AsyncClient.request", mock_request):
            client.get("/context-manager/data", headers=bearer_headers)
        headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
        assert "host" not in headers_lower

    @respx.mock
    def test_proxy_preserves_other_headers(self, client, bearer_headers):
        captured = {}

        async def capture(request):
            captured["headers"] = dict(request.headers)
            return httpx.Response(200, json={"ok": True})

        respx.get("http://localhost:3847/data").mock(side_effect=capture)
        client.get(
            "/context-manager/data",
            headers={**bearer_headers, "x-custom": "my-value"},
        )
        headers_lower = {k.lower(): v for k, v in captured["headers"].items()}
        assert headers_lower.get("x-custom") == "my-value"

    @respx.mock
    def test_proxy_preserves_query_params(self, client, bearer_headers):
        captured = {}

        async def capture(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"ok": True})

        respx.get().mock(side_effect=capture)
        client.get("/context-manager/data?foo=bar&baz=1", headers=bearer_headers)
        assert "foo=bar" in captured["url"]
        assert "baz=1" in captured["url"]

    @respx.mock
    def test_proxy_path_routing(self, client, bearer_headers):
        captured = {}

        async def capture(request):
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"ok": True})

        respx.get().mock(side_effect=capture)
        client.get("/context-manager/some/deep/path", headers=bearer_headers)
        assert "/some/deep/path" in captured["url"]


# ══════════════════════════════════════════════════════════════════════
# 5. ConfigAndProxyIntegration — combined behaviour
# ══════════════════════════════════════════════════════════════════════

class TestConfigAndProxyIntegration:

    def test_cm_proxy_no_auth_returns_401(self, client):
        r = client.get("/context-manager/health")
        assert r.status_code == 401
        assert r.json() == {"error": "unauthorized"}

    def test_cm_proxy_with_bearer_passes(self, client, bearer_headers):
        with respx.mock:
            respx.get("http://localhost:3847/health").mock(
                return_value=httpx.Response(200, json={"ok": True})
            )
            r = client.get("/context-manager/health", headers=bearer_headers)
            assert r.status_code == 200

    def test_mcp_config_reflects_current_config(self, client):
        r = client.get("/mcp-config")
        routes = r.json()["routes"]
        assert "/context-manager" in routes
        assert routes["/context-manager"]["auth"] == ["bearer"]
        assert routes["/context-manager"]["transport"] == "proxy"

    def test_mcp_config_lists_all_transport_types(self, client):
        r = client.get("/mcp-config")
        transports = {cfg["transport"] for cfg in r.json()["routes"].values()}
        assert "streamable-http" in transports
        assert "sse" in transports
        assert "sse-messages" in transports
        assert "proxy" in transports

    @respx.mock
    def test_proxy_to_cm_other_method_returns_502(self, client, bearer_headers):
        respx.head("http://localhost:3847/health").mock(
            side_effect=httpx.ConnectError("refused")
        )
        r = client.head("/context-manager/health", headers=bearer_headers)
        assert r.status_code == 502

    def test_daemon_status_probes_cm_health(self, client, monkeypatch):
        calls = []

        async def tracking_call(name, *args, **kwargs):
            calls.append(name)
            return {"status": "ok"}

        monkeypatch.setattr(
            "mnemostroma.integration.mcp_oauth_adapter.safe_ipc_call",
            tracking_call,
        )
        client.get("/mcp-config")
        assert "health" in calls
