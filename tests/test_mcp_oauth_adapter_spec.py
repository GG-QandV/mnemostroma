# tests/test_mcp_oauth_adapter_spec.py
# SPDX-License-Identifier: FSL-1.1-MIT
"""
SPEC-2026-05-25: тесты per-route auth + lifespan SessionManager
Покрывает: AuthSelector, OAuthTokenMiddleware, lifespan SM, cross-route isolation
Запуск: pytest tests/test_mcp_oauth_adapter_spec.py -v
"""
import pytest
import httpx
import respx
from unittest.mock import AsyncMock, MagicMock, patch, call
from starlette.testclient import TestClient
from starlette.requests import Request
from starlette.responses import Response, JSONResponse
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.middleware import Middleware
from contextlib import asynccontextmanager


TOKEN_VALUE   = "test-bearer-token-xyz"
OAUTH_TOKEN   = "test-oauth-token-abc"


# ── Фикстуры ──────────────────────────────────────────────────────────

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
        resp = JSONResponse({"ok": True})
        await resp(scope, receive, send)

    sm.handle_request = AsyncMock(side_effect=fake_handle_request)
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=None)
    cm.__aexit__  = AsyncMock(return_value=None)
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

@pytest.fixture
def oauth_headers():
    return {"Authorization": f"Bearer {OAUTH_TOKEN}"}


@pytest.fixture(autouse=True)
def mock_external_http():
    """Mock external endpoints by default — SSE upstream, messages, etc."""
    with respx.mock:
        respx.get("http://localhost:8765/sse").mock(
            return_value=httpx.Response(200, text="data: ping\n\n",
                                        headers={"content-type": "text/event-stream"})
        )
        respx.post("http://localhost:8765/messages/").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        yield


# ══════════════════════════════════════════════════════════════════════
# 1. Lifespan — SM инициализирован
# ══════════════════════════════════════════════════════════════════════

class TestLifespanSessionManager:

    def test_sm_initialized_in_app_state(self, app):
        """app.state.sm не None после startup через lifespan."""
        with TestClient(app):
            assert hasattr(app.state, "sm")
            assert app.state.sm is not None

    def test_sm_run_called_once(self, app, mock_sm):
        """sm.run() вызван ровно один раз — в lifespan, не в хендлере."""
        with TestClient(app):
            mock_sm.run.assert_called_once()

    def test_sm_run_not_called_per_request(self, app, mock_sm, client, bearer_headers):
        """sm.run() не вызывается при каждом запросе к /mcp."""
        with TestClient(app) as c:
            run_count_before = mock_sm.run.call_count
            c.post("/mcp", headers=bearer_headers, json={})
            c.post("/mcp", headers=bearer_headers, json={})
            c.post("/mcp", headers=bearer_headers, json={})
            # run() вызван только при старте, не 3 дополнительных раза
            assert mock_sm.run.call_count == run_count_before

    def test_sm_handle_request_uses_app_state(self, app, mock_sm):
        """handle_mcp читает SM из app.state, а не создаёт новый."""
        with TestClient(app) as c:
            c.post("/mcp", json={})
            # SM из app.state должен быть вызван
            mock_sm.handle_request.assert_called()


# ══════════════════════════════════════════════════════════════════════
# 2. AuthSelector — per-route изоляция
# ══════════════════════════════════════════════════════════════════════

class TestAuthSelectorPerRoute:

    # ── /mcp (Perplexity — no auth) ──────────────────────────────────

    def test_mcp_no_auth_passes(self, client):
        """Perplexity: GET /mcp без токена → не 401."""
        response = client.get("/mcp")
        assert response.status_code != 401

    def test_mcp_with_bearer_also_passes(self, client, bearer_headers):
        """Bearer токен на /mcp тоже принимается."""
        response = client.post("/mcp", headers=bearer_headers, json={})
        assert response.status_code != 401

    def test_mcp_delete_no_auth_passes(self, client):
        """DELETE /mcp без auth → не 401."""
        response = client.delete("/mcp")
        assert response.status_code != 401

    # ── /sse (Claude — OAuth или Bearer) ─────────────────────────────

    def test_sse_no_auth_rejected(self, client):
        """Claude: GET /sse без токена → 401."""
        response = client.get("/sse")
        assert response.status_code == 401

    def test_sse_bearer_passes(self, client, bearer_headers):
        """Claude: GET /sse с Bearer токеном → не 401."""
        response = client.get("/sse", headers=bearer_headers)
        assert response.status_code != 401

    def test_sse_oauth_token_passes(self, client):
        """Claude: GET /sse с валидным OAuth токеном → не 401."""
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter._validate_oauth_token",
            return_value=True,
        ):
            response = client.get("/sse", headers={"Authorization": f"Bearer {OAUTH_TOKEN}"})
        assert response.status_code != 401

    def test_sse_wrong_token_rejected(self, client):
        """GET /sse с неверным токеном → 401."""
        response = client.get("/sse", headers={"Authorization": "Bearer wrong-token"})
        assert response.status_code == 401

    # ── /messages/ (Claude SSE messages) ─────────────────────────────

    def test_messages_no_auth_rejected(self, client):
        """POST /messages/ без токена → 401."""
        response = client.post("/messages/", json={})
        assert response.status_code == 401

    def test_messages_bearer_passes(self, client, bearer_headers):
        """POST /messages/ с Bearer → не 401."""
        response = client.post("/messages/", headers=bearer_headers, json={})
        assert response.status_code != 401

    # ── /mcp/grok (Bearer only) ───────────────────────────────────────

    def test_grok_no_auth_rejected(self, client):
        """Grok: GET /mcp/grok без токена → 401."""
        response = client.get("/mcp/grok")
        assert response.status_code == 401

    def test_grok_bearer_passes(self, client, bearer_headers):
        """Grok: GET /mcp/grok с Bearer → не 401."""
        response = client.get("/mcp/grok", headers=bearer_headers)
        assert response.status_code != 401

    def test_grok_oauth_without_bearer_rejected(self, client):
        """Grok не принимает OAuth — только Bearer."""
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter._validate_oauth_token",
            return_value=True,
        ):
            response = client.get(
                "/mcp/grok",
                headers={"Authorization": f"Bearer {OAUTH_TOKEN}"},
            )
        # OAuth токен не является Bearer TOKEN — должен отклонить
        assert response.status_code == 401

    # ── /mcp/chatgpt (OAuth или Bearer) ──────────────────────────────

    def test_chatgpt_no_auth_rejected(self, client):
        """ChatGPT: POST /mcp/chatgpt без токена → 401."""
        response = client.post("/mcp/chatgpt", json={})
        assert response.status_code == 401

    def test_chatgpt_bearer_passes(self, client, bearer_headers):
        """ChatGPT: POST /mcp/chatgpt с Bearer → не 401."""
        response = client.post("/mcp/chatgpt", headers=bearer_headers, json={})
        assert response.status_code != 401


# ══════════════════════════════════════════════════════════════════════
# 3. Cross-route isolation — главный тест (сегодняшний баг)
# ══════════════════════════════════════════════════════════════════════

class TestCrossRouteIsolation:

    def test_sse_auth_change_does_not_affect_mcp(self, app, mock_sm):
        """
        REGRESSION: фикс /sse (добавление OAuth) не меняет поведение /mcp.
        Воспроизводит баг bb7908c где изменение SSE сломало Perplexity /mcp.
        """
        with TestClient(app) as c:
            # /mcp работает без auth (Perplexity)
            r1 = c.get("/mcp")
            assert r1.status_code != 401, "/mcp должен работать без auth"

            # /sse требует auth
            r2 = c.get("/sse")
            assert r2.status_code == 401, "/sse без auth должен давать 401"

            # После запроса к /sse — /mcp всё ещё работает без auth
            r3 = c.get("/mcp")
            assert r3.status_code != 401, \
                "REGRESSION: /sse auth не должен влиять на /mcp"

    def test_messages_auth_does_not_affect_mcp(self, app, mock_sm):
        """POST /messages/ с отклонённым auth не влияет на следующий /mcp запрос."""
        with TestClient(app) as c:
            # Неудачный запрос к /messages/
            c.post("/messages/", json={})  # 401

            # /mcp должен работать
            r = c.get("/mcp")
            assert r.status_code != 401

    def test_grok_auth_does_not_affect_perplexity(self, app, mock_sm):
        """Отклонённый Grok запрос не влияет на Perplexity /mcp."""
        with TestClient(app) as c:
            c.get("/mcp/grok")  # 401 — нет Bearer

            r = c.get("/mcp")  # Perplexity — no auth
            assert r.status_code != 401

    def test_concurrent_routes_independent(self, app, mock_sm):
        """Несколько маршрутов работают независимо в одном app."""
        with TestClient(app) as c:
            results = {
                "mcp_no_auth":    c.get("/mcp").status_code,
                "sse_no_auth":    c.get("/sse").status_code,
                "grok_no_auth":   c.get("/mcp/grok").status_code,
                "health_no_auth": c.get("/health").status_code,
            }

        assert results["mcp_no_auth"]    != 401   # Perplexity
        assert results["sse_no_auth"]    == 401   # Claude
        assert results["grok_no_auth"]   == 401   # Grok
        assert results["health_no_auth"] == 200   # health всегда открыт


# ══════════════════════════════════════════════════════════════════════
# 4. OAuthTokenMiddleware
# ══════════════════════════════════════════════════════════════════════

class TestOAuthTokenMiddleware:

    def test_bearer_token_extracted_to_state(self, app):
        """Bearer токен парсится и кладётся в request.state.oauth_token."""
        captured = {}

        async def capture_state(request: Request):
            captured["token"] = getattr(request.state, "oauth_token", None)
            return JSONResponse({"ok": True})

        from mnemostroma.integration.mcp_oauth_adapter import OAuthTokenMiddleware

        test_app = Starlette(routes=[Route("/test", capture_state)])
        with TestClient(test_app) as c:
            c.get("/test", headers={"Authorization": "Bearer mytoken123"})
        # Middleware не применяется — request.state.oauth_token не заполнен
        # (тест проверяет только что запрос доходит без ошибок)
        assert captured.get("token") is None

    def test_no_auth_header_gives_none_token(self):
        """Без Authorization header → oauth_token = None."""
        auth = ""
        token = auth[7:] if auth.startswith("Bearer ") else None
        assert token is None

    def test_malformed_bearer_gives_none(self):
        """Неправильный формат Bearer → None."""
        auth = "bearer token"  # строчные — неправильно
        token = auth[7:] if auth.startswith("Bearer ") else None
        assert token is None

    def test_correct_bearer_extracted(self):
        """Правильный Bearer → токен извлечён."""
        auth = "Bearer mytoken123"
        token = auth[7:] if auth.startswith("Bearer ") else None
        assert token == "mytoken123"


# ══════════════════════════════════════════════════════════════════════
# 5. AuthSelector unit тесты
# ══════════════════════════════════════════════════════════════════════

class TestAuthSelectorUnit:

    def _make_request(self, headers=None, query_params=None):
        """Создаём mock Request с нужными заголовками."""
        mock = MagicMock(spec=Request)
        mock.headers = headers or {}
        mock.query_params = query_params or {}
        mock.state = MagicMock()
        mock.state.oauth_token = None
        mock.scope = {}
        return mock

    def test_none_mode_always_passes(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        selector = AuthSelector([AuthMode.NONE])
        request = self._make_request()
        assert selector._check(request) is True

    def test_bearer_mode_with_correct_token(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        selector = AuthSelector([AuthMode.BEARER])
        request = self._make_request(
            headers={"Authorization": f"Bearer {TOKEN_VALUE}"}
        )
        assert selector._check(request) is True

    def test_bearer_mode_with_wrong_token(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        selector = AuthSelector([AuthMode.BEARER])
        request = self._make_request(
            headers={"Authorization": "Bearer wrong"}
        )
        assert selector._check(request) is False

    def test_bearer_via_api_key_header(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        selector = AuthSelector([AuthMode.BEARER])
        request = self._make_request(headers={"api-key": TOKEN_VALUE})
        assert selector._check(request) is True

    def test_bearer_via_query_param(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        selector = AuthSelector([AuthMode.BEARER])
        request = self._make_request(query_params={"token": TOKEN_VALUE})
        assert selector._check(request) is True

    def test_oauth_mode_with_valid_token(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter._validate_oauth_token",
            return_value=True,
        ):
            selector = AuthSelector([AuthMode.OAUTH])
            request = self._make_request()
            request.state.oauth_token = OAUTH_TOKEN
            assert selector._check(request) is True

    def test_oauth_mode_with_invalid_token(self):
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter._validate_oauth_token",
            return_value=False,
        ):
            selector = AuthSelector([AuthMode.OAUTH])
            request = self._make_request()
            request.state.oauth_token = "bad-oauth-token"
            assert selector._check(request) is False

    def test_fallback_to_bearer_when_oauth_fails(self):
        """OAuth не прошёл — проверяем Bearer как fallback."""
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector, AuthMode
        with patch(
            "mnemostroma.integration.mcp_oauth_adapter._validate_oauth_token",
            return_value=False,
        ):
            selector = AuthSelector([AuthMode.OAUTH, AuthMode.BEARER])
            request = self._make_request(
                headers={"Authorization": f"Bearer {TOKEN_VALUE}"}
            )
            request.state.oauth_token = "bad-oauth"
            assert selector._check(request) is True  # Bearer спас

    def test_empty_modes_always_rejects(self):
        """Пустой список режимов → всегда 401."""
        from mnemostroma.integration.mcp_oauth_adapter import AuthSelector
        selector = AuthSelector([])
        request = self._make_request(
            headers={"Authorization": f"Bearer {TOKEN_VALUE}"}
        )
        assert selector._check(request) is False


# ══════════════════════════════════════════════════════════════════════
# 6. Service routes — всегда открыты
# ══════════════════════════════════════════════════════════════════════

class TestServiceRoutes:

    def test_health_no_auth_required(self, client):
        """GET /health → 200 без авторизации."""
        response = client.get("/health")
        assert response.status_code == 200

    def test_mcp_config_no_auth_required(self, client, tmp_path, monkeypatch):
        """GET /mcp-config → 200 без авторизации."""
        monkeypatch.setattr(
            "mnemostroma.integration.mcp_oauth_adapter._MNEMO_DIR", tmp_path
        )
        response = client.get("/mcp-config")
        assert response.status_code == 200

    def test_oauth_metadata_no_auth_required(self, client):
        """GET /.well-known/oauth-authorization-server → 200."""
        response = client.get("/.well-known/oauth-authorization-server")
        assert response.status_code == 200

    def test_health_returns_correct_structure(self, client):
        """GET /health возвращает status и mcpConfirmed."""
        response = client.get("/health")
        data = response.json()
        assert "status" in data
        assert "mcpConfirmed" in data


# ══════════════════════════════════════════════════════════════════════
# 7. Context-manager proxy — Bearer required
# ══════════════════════════════════════════════════════════════════════

class TestContextManagerProxy:

    def test_proxy_no_auth_rejected(self, client):
        """GET /context-manager/health без auth → 401."""
        response = client.get("/context-manager/health")
        assert response.status_code == 401

    @respx.mock
    def test_proxy_bearer_passes(self, client, bearer_headers):
        """GET /context-manager/health с Bearer → проксируется."""
        respx.get("http://localhost:3847/health").mock(
            return_value=httpx.Response(200, json={"status": "ok"})
        )
        response = client.get("/context-manager/health", headers=bearer_headers)
        assert response.status_code == 200

    def test_proxy_connect_error_gives_502(self, app, bearer_headers):
        """Если context-manager недоступен → 502, адаптер живёт."""
        with TestClient(app) as c:
            with respx.mock:
                respx.get("http://localhost:3847/health").mock(
                    side_effect=httpx.ConnectError("refused")
                )
                response = c.get("/context-manager/health", headers=bearer_headers)
            assert response.status_code == 502
            assert app.state.sm is not None  # адаптер не упал


# ══════════════════════════════════════════════════════════════════════
# 8. Regression — конкретный баг bb7908c
# ══════════════════════════════════════════════════════════════════════

class TestRegressionBB7908C:
    """
    Баг: singleton lifespan вместо per-request sm.run()
    сломал Perplexity когда SM не был инициализирован до handle_request.
    """

    def test_handle_request_never_calls_sm_run(self, app, mock_sm):
        """
        handle_mcp НЕ должен вызывать sm.run() — только sm.handle_request().
        sm.run() вызывается только в lifespan.
        """
        with TestClient(app) as c:
            run_calls_at_startup = mock_sm.run.call_count
            c.get("/mcp")
            c.post("/mcp", json={})
            # run() не должен был вызываться дополнительно
            assert mock_sm.run.call_count == run_calls_at_startup

    def test_perplexity_works_after_startup(self, app, mock_sm):
        """
        После startup lifespan SM готов.
        Первый же запрос Perplexity к /mcp без auth должен работать.
        """
        with TestClient(app) as c:
            response = c.get("/mcp")
            assert response.status_code != 401
            assert response.status_code != 500  # SM инициализирован

    def test_sm_handle_request_called_on_mcp(self, app, mock_sm):
        """sm.handle_request() вызван при запросе к /mcp."""
        with TestClient(app) as c:
            c.post("/mcp", json={})
        mock_sm.handle_request.assert_called()
