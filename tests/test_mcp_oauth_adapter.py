# SPDX-License-Identifier: FSL-1.1-MIT
import base64
import hashlib
import json
import secrets
import time
import pytest
import httpx
from starlette.testclient import TestClient
from mnemostroma.integration import mcp_oauth_adapter
from mnemostroma.integration.tunnel import token


# Mock Response class for matching httpx interfaces
class MockResponse:
    def __init__(self, status_code, content, headers=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}

    async def aiter_bytes(self):
        # Для SSE стриминга
        yield self.content

    def __aenter__(self):
        return self

    def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.fixture(autouse=True)
def mock_tunnel_token(monkeypatch, tmp_path):
    # Изолируем tunnel_token для тестов
    fake_token_path = tmp_path / "tunnel_token"
    monkeypatch.setattr(token, "TUNNEL_TOKEN_PATH", fake_token_path)
    # Очищаем ин-мемори состояние адаптера перед каждым тестом
    monkeypatch.setattr(mcp_oauth_adapter, "_clients", {})
    monkeypatch.setattr(mcp_oauth_adapter, "_codes", {})
    monkeypatch.setattr(mcp_oauth_adapter, "_tokens", {})


@pytest.fixture(autouse=True)
def mock_httpx_client(monkeypatch):
    """Мокируем httpx.AsyncClient для предотвращения реальных сетевых запросов."""
    async def mock_request(self, method, url, **kwargs):
        if "/mcp" in str(url):
            return MockResponse(200, b'{"ok": true}', {"content-type": "application/json"})
        return MockResponse(404, b"Not Found")

    class MockStreamContext:
        def __init__(self, method, url, **kwargs):
            self.method = method
            self.url = url

        async def __aenter__(self):
            if "/sse" in str(self.url):
                return MockResponse(200, b"data: ping\n\n", {"content-type": "text/event-stream"})
            return MockResponse(404, b"Not Found")

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(httpx.AsyncClient, "request", mock_request)
    monkeypatch.setattr(httpx.AsyncClient, "stream", MockStreamContext)


# ── Группа 1: Базовые endpoints ──────────────────────────────────────────────

def test_health():
    client = TestClient(mcp_oauth_adapter.app)
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["mcpConfirmed"] is True
    assert data["daemon"] == "ok"
    assert "routes" in data
    assert "active_count" in data["routes"]
    assert "paths" in data["routes"]
    assert "reload" in data
    assert "total_attempts" in data["reload"]


# ── Группа 2: RFC 8414 OAuth Metadata ────────────────────────────────────────

def test_oauth_metadata_keys():
    client = TestClient(mcp_oauth_adapter.app)
    r = client.get("/.well-known/oauth-authorization-server")
    assert r.status_code == 200
    data = r.json()
    assert "issuer" in data
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "registration_endpoint" in data
    assert "code_challenge_methods_supported" in data
    assert data["response_types_supported"] == ["code"]
    assert data["grant_types_supported"] == ["authorization_code"]


# ── Группа 3: RFC 9728 Protected Resource ────────────────────────────────────

def test_protected_resource_metadata():
    client = TestClient(mcp_oauth_adapter.app)
    r = client.get("/.well-known/oauth-protected-resource")
    assert r.status_code == 200
    data = r.json()
    assert "resource" in data
    assert "authorization_servers" in data
    assert data["bearer_methods_supported"] == ["header"]


# ── Группа 4: Dynamic Client Registration (DCR) ──────────────────────────────

def test_register_returns_client_id():
    client = TestClient(mcp_oauth_adapter.app)
    payload = {"redirect_uris": ["https://claude.ai/oauth"]}
    r = client.post("/register", json=payload)
    assert r.status_code == 201
    data = r.json()
    assert "client_id" in data
    assert "client_secret" in data
    assert data["redirect_uris"] == ["https://claude.ai/oauth"]


def test_register_stores_redirect_uris():
    client = TestClient(mcp_oauth_adapter.app)
    payload = {"redirect_uris": ["https://chatgpt.com/connector/oauth/123"]}
    r = client.post("/register", json=payload)
    client_id = r.json()["client_id"]
    assert client_id in mcp_oauth_adapter._clients
    assert mcp_oauth_adapter._clients[client_id]["redirect_uris"] == [
        "https://chatgpt.com/connector/oauth/123"
    ]


def test_register_invalid_json():
    client = TestClient(mcp_oauth_adapter.app)
    r = client.post("/register", content="invalid-json-format")
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request"}


# ── Группа 5: PKCE Flow (полный цикл) ─────────────────────────────────────────

def test_full_oauth_flow(monkeypatch):
    client = TestClient(mcp_oauth_adapter.app)
    monkeypatch.setattr("webbrowser.open", lambda url: True)

    # 1. Регистрация
    reg_r = client.post("/register", json={"redirect_uris": ["https://oauth-callback"]})
    client_id = reg_r.json()["client_id"]

    # 2. GET /authorize -> 200 Consent Screen
    verifier = "abcdefghijklmnopqrstuvwxyz1234567890-pkce-verifier-string"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth_params = {
        "client_id": client_id,
        "redirect_uri": "https://oauth-callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_type": "code",
        "state": "state-123"
    }
    r = client.get("/authorize", params=auth_params)
    assert r.status_code == 200
    assert "Mnemostroma — Authorization Request" in r.text
    assert client_id in r.text

    # 3. POST /authorize/confirm (кнопка согласия) -> 302 с кодом
    confirm_params = {
        "client_id": client_id,
        "redirect_uri": "https://oauth-callback",
        "code_challenge": challenge,
        "state": "state-123"
    }
    confirm_post = client.post("/authorize/confirm", data=confirm_params, follow_redirects=False)
    assert confirm_post.status_code == 302
    loc = confirm_post.headers["location"]
    assert "code=" in loc
    code = loc.split("code=")[1].split("&")[0]

    # 4. POST /token (обмен кода на токен)
    token_r = client.post("/token", data={"code": code, "code_verifier": verifier})
    assert token_r.status_code == 200
    token_data = token_r.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] == 3600


def test_pkce_invalid_verifier(monkeypatch):
    client = TestClient(mcp_oauth_adapter.app)
    monkeypatch.setattr("webbrowser.open", lambda url: True)

    reg_r = client.post("/register", json={"redirect_uris": ["https://oauth-callback"]})
    client_id = reg_r.json()["client_id"]

    verifier = "abcdefghijklmnopqrstuvwxyz1234567890-pkce-verifier-string"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth_params = {
        "client_id": client_id,
        "redirect_uri": "https://oauth-callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_type": "code",
    }
    client.get("/authorize", params=auth_params)

    confirm_params = {
        "client_id": client_id,
        "redirect_uri": "https://oauth-callback",
        "code_challenge": challenge,
    }
    confirm_post = client.post("/authorize/confirm", data=confirm_params, follow_redirects=False)
    code = confirm_post.headers["location"].split("code=")[1].split("&")[0]

    # POST /token с неверным verifier
    token_r = client.post("/token", data={"code": code, "code_verifier": "wrong-verifier"})
    assert token_r.status_code == 400
    assert token_r.json()["error"] == "invalid_grant"


def test_expired_code(monkeypatch):
    client = TestClient(mcp_oauth_adapter.app)
    monkeypatch.setattr("webbrowser.open", lambda url: True)

    reg_r = client.post("/register", json={"redirect_uris": ["https://oauth-callback"]})
    client_id = reg_r.json()["client_id"]

    verifier = "abcdefghijklmnopqrstuvwxyz1234567890-pkce-verifier-string"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth_params = {
        "client_id": client_id,
        "redirect_uri": "https://oauth-callback",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "response_type": "code",
    }
    client.get("/authorize", params=auth_params)

    confirm_params = {
        "client_id": client_id,
        "redirect_uri": "https://oauth-callback",
        "code_challenge": challenge,
    }
    confirm_post = client.post("/authorize/confirm", data=confirm_params, follow_redirects=False)
    code = confirm_post.headers["location"].split("code=")[1].split("&")[0]

    # Эмулируем истечение времени действия кода (> 300 секунд)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 301)

    token_r = client.post("/token", data={"code": code, "code_verifier": verifier})
    assert token_r.status_code == 400
    assert token_r.json()["error"] == "invalid_grant"


def test_authorize_missing_params():
    client = TestClient(mcp_oauth_adapter.app)
    # Отсутствует code_challenge
    r = client.get("/authorize?client_id=123&redirect_uri=https://callback&response_type=code")
    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request"}


def test_authorize_invalid_method():
    client = TestClient(mcp_oauth_adapter.app)
    # code_challenge_method = plain (не поддерживается)
    r = client.get(
        "/authorize?client_id=123&redirect_uri=https://callback&response_type=code"
        "&code_challenge=xyz&code_challenge_method=plain"
    )
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_request"


def test_authorize_confirm_page_html():
    client = TestClient(mcp_oauth_adapter.app)
    r = client.get("/authorize/confirm?code=some-code&state=some-state")
    assert r.status_code == 200
    assert "Mnemostroma — Authorization Request" in r.text


def test_authorize_confirm_post_success():
    client = TestClient(mcp_oauth_adapter.app)
    # Создадим фиктивный код во внутренней базе
    mcp_oauth_adapter._codes["test-code"] = {
        "client_id": "client-1",
        "pkce_challenge": "challenge-1",
        "redirect_uri": "https://callback",
        "expires": time.time() + 300
    }
    r = client.post("/authorize/confirm?code=test-code")
    assert r.status_code == 200
    assert "Access Granted!" in r.text


def test_authorize_confirm_post_invalid_code():
    client = TestClient(mcp_oauth_adapter.app)
    r = client.post("/authorize/confirm?code=invalid-or-expired-code")
    assert r.status_code == 400
    assert "Authorization session expired or invalid" in r.text


# ── Группа 6: MCP HTTP Auth (per-route isolation) ───────────────────────────

_MCP_LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
_MCP_JSON_ACCEPT = {"Accept": "application/json"}


def test_mcp_no_auth():
    """Perplexity: /mcp is NONE auth → доступ без токена"""
    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.post("/mcp", json=_MCP_LIST_TOOLS, headers=_MCP_JSON_ACCEPT)
        assert r.status_code == 200
        data = r.json()
        assert data["jsonrpc"] == "2.0"
        assert len(data["result"]["tools"]) > 0


def test_mcp_chatgpt_no_auth():
    """ChatGPT: /mcp/chatgpt без токена → 401"""
    client = TestClient(mcp_oauth_adapter.app)
    r = client.post("/mcp/chatgpt", json=_MCP_LIST_TOOLS, headers=_MCP_JSON_ACCEPT)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_mcp_chatgpt_with_oauth_token():
    """ChatGPT: /mcp/chatgpt с OAuth Bearer токеном → 200"""
    mcp_oauth_adapter._tokens["valid-oauth-token"] = {
        "client_id": "c1",
        "expires": time.time() + 3600,
    }
    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.post(
            "/mcp/chatgpt",
            json=_MCP_LIST_TOOLS,
            headers={**_MCP_JSON_ACCEPT, "Authorization": "Bearer valid-oauth-token"},
        )
        assert r.status_code == 200
        assert r.json()["jsonrpc"] == "2.0"


def test_mcp_grok_no_auth():
    """Grok: /mcp/grok без токена → 401"""
    client = TestClient(mcp_oauth_adapter.app)
    r = client.post("/mcp/grok", json=_MCP_LIST_TOOLS, headers=_MCP_JSON_ACCEPT)
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_mcp_grok_with_tunnel_token():
    """Grok: /mcp/grok с tunnel token (BEARER only) → 200"""
    tok = token.get_or_create_tunnel_token()
    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.post(
            "/mcp/grok",
            json=_MCP_LIST_TOOLS,
            headers={**_MCP_JSON_ACCEPT, "Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        assert r.json()["jsonrpc"] == "2.0"


def test_mcp_grok_with_invalid_token():
    """Grok: /mcp/grok с невалидным Bearer → 401"""
    client = TestClient(mcp_oauth_adapter.app)
    r = client.post(
        "/mcp/grok",
        json=_MCP_LIST_TOOLS,
        headers={**_MCP_JSON_ACCEPT, "Authorization": "Bearer wrong-token"},
    )
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


# ── Группа 6: SSE Auth ──────────────────────────────────────────────────────

def test_sse_no_auth():
    """SSE без токена → 401 (требуется OAUTH|BEARER)"""
    client = TestClient(mcp_oauth_adapter.app)
    r = client.get("/sse")
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


def test_sse_with_tunnel_token():
    """SSE с tunnel token (BEARER) → 200"""
    tok = token.get_or_create_tunnel_token()
    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.get("/sse", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        assert "data: ping" in r.text


def test_sse_invalid_token():
    """SSE с невалидным токеном → 401"""
    client = TestClient(mcp_oauth_adapter.app)
    r = client.get("/sse", headers={"Authorization": "Bearer wrong-token"})
    assert r.status_code == 401
    assert r.json() == {"error": "unauthorized"}


# ── Группа 7: Token Expiry ──────────────────────────────────────────────────

def test_oauth_token_expires(monkeypatch):
    """OAuth Bearer token expiry на /mcp/chatgpt"""
    mcp_oauth_adapter._tokens["expiring-token"] = {
        "client_id": "c1",
        "expires": time.time() + 100,
    }

    with TestClient(mcp_oauth_adapter.app) as client:
        r1 = client.post(
            "/mcp/chatgpt",
            json=_MCP_LIST_TOOLS,
            headers={**_MCP_JSON_ACCEPT, "Authorization": "Bearer expiring-token"},
        )
        assert r1.status_code == 200
        assert r1.json()["jsonrpc"] == "2.0"

        now = time.time()
        monkeypatch.setattr(time, "time", lambda: now + 101)

        r2 = client.post(
            "/mcp/chatgpt",
            json=_MCP_LIST_TOOLS,
            headers={**_MCP_JSON_ACCEPT, "Authorization": "Bearer expiring-token"},
        )
        assert r2.status_code == 401
        assert r2.json() == {"error": "unauthorized"}


# ── Группа 8: Сквозная трассировка запроса ──────────────────────────────────

def test_oauth_and_proxy_traceroute_flow(monkeypatch, tmp_path):
    """Сквозной тест: DCR → Authorization → Consent → Token Exchange → MCP + SSE"""
    fake_token_dir = tmp_path / ".mnemostroma"
    fake_token_dir.mkdir(parents=True, exist_ok=True)
    fake_sse_token = fake_token_dir / "sse_token"
    fake_sse_token.write_text("my-internal-secure-token", encoding="utf-8")
    monkeypatch.setattr(mcp_oauth_adapter, "_MNEMO_DIR", fake_token_dir)
    monkeypatch.setattr(mcp_oauth_adapter, "_SSE_TOKEN_PATH", fake_sse_token)
    monkeypatch.setattr("webbrowser.open", lambda url: True)

    client = TestClient(mcp_oauth_adapter.app)

    # Шаг A: DCR (RFC 7591)
    reg_r = client.post("/register", json={"redirect_uris": ["https://oauth-callback"]})
    assert reg_r.status_code == 201
    reg_data = reg_r.json()
    assert "client_id" in reg_data
    client_id = reg_data["client_id"]

    # Шаг B: PKCE Authorize (RFC 7636)
    verifier = "my-secure-pkce-verifier-string-1234567890-abcdef"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth_r = client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": "https://oauth-callback",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "response_type": "code",
            "state": "state-trace-123",
        },
    )
    assert auth_r.status_code == 200
    assert "Mnemostroma — Authorization Request" in auth_r.text

    # Шаг C: Consent
    confirm_r = client.post(
        "/authorize/confirm",
        data={
            "client_id": client_id,
            "redirect_uri": "https://oauth-callback",
            "code_challenge": challenge,
            "state": "state-trace-123",
        },
        follow_redirects=False,
    )
    assert confirm_r.status_code == 302
    redirect_url = confirm_r.headers["location"]
    assert "code=" in redirect_url
    code = redirect_url.split("code=")[1].split("&")[0]

    # Шаг D: Token Exchange
    token_r = client.post("/token", data={"code": code, "code_verifier": verifier})
    assert token_r.status_code == 200
    token_data = token_r.json()
    assert "access_token" in token_data
    access_token = token_data["access_token"]

    # Шаг E: MCP call via /mcp/chatgpt (OAuth)
    with TestClient(mcp_oauth_adapter.app) as mcp_client:
        mcp_r = mcp_client.post(
            "/mcp/chatgpt",
            json=_MCP_LIST_TOOLS,
            headers={**_MCP_JSON_ACCEPT, "Authorization": f"Bearer {access_token}"},
        )
        assert mcp_r.status_code == 200
        data = mcp_r.json()
        assert data["jsonrpc"] == "2.0"
        assert len(data["result"]["tools"]) > 0

    # Шаг F: SSE proxy with OAuth token
    captured_streams = []

    class TraceMockStreamContext:
        def __init__(self, method, url, **kwargs):
            captured_streams.append({
                "method": method,
                "url": str(url),
                "headers": kwargs.get("headers", {}),
            })

        async def __aenter__(self):
            return MockResponse(200, b"data: event-trace\n\n", {"content-type": "text/event-stream"})

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

    monkeypatch.setattr(httpx.AsyncClient, "stream", TraceMockStreamContext)

    sse_r = client.get(
        "/sse",
        headers={"Authorization": f"Bearer {access_token}", "X-SSE-Client": "sse-trace-value"},
    )
    assert sse_r.status_code == 200
    assert "data: event-trace" in sse_r.text

    assert len(captured_streams) == 1
    stream = captured_streams[0]
    assert stream["method"] == "GET"
    assert stream["url"] == "http://localhost:8765/sse"
    stream_headers = {k.lower(): v for k, v in stream["headers"].items()}
    assert stream_headers["authorization"] == "Bearer my-internal-secure-token"
    assert stream_headers["x-sse-client"] == "sse-trace-value"
    assert "host" not in stream_headers


def test_mcp_handler_injects_accept_header():
    """Тест inject_accept_header: проверяет, что заголовок Accept перезаписывается/добавляется."""
    with TestClient(mcp_oauth_adapter.app) as client:
        # 1. Запрос без заголовка Accept
        r_no_accept = client.post(
            "/mcp",
            json=_MCP_LIST_TOOLS,
        )
        assert r_no_accept.status_code == 200
        assert r_no_accept.json()["jsonrpc"] == "2.0"

        # 2. Запрос с заголовком Accept: */*
        r_star_accept = client.post(
            "/mcp",
            json=_MCP_LIST_TOOLS,
            headers={"Accept": "*/*"}
        )
        assert r_star_accept.status_code == 200
        assert r_star_accept.json()["jsonrpc"] == "2.0"

        # 3. Запрос с заголовком Accept: text/html (неверный)
        r_html_accept = client.post(
            "/mcp",
            json=_MCP_LIST_TOOLS,
            headers={"Accept": "text/html"}
        )
        assert r_html_accept.status_code == 200
        assert r_html_accept.json()["jsonrpc"] == "2.0"


def test_tunnel_status_endpoint_returns_active(monkeypatch, tmp_path):
    """Verify GET /tunnel/status returns correct tunnel state and PID."""
    from pathlib import Path
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)

    # 1. Stopped state
    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.get("/tunnel/status")
        assert r.status_code == 200
        data = r.json()
        assert data["active"] is False
        assert data["url"] is None
        assert data["pid"] is None

    # 2. Running state
    (mnemo_dir / "tunnel_url").write_text("https://active-tunnel.serveo.net", encoding="utf-8")
    (mnemo_dir / "serveo_tunnel.pid").write_text("99999", encoding="utf-8")

    # Mock psutil.pid_exists to return True for 99999
    import psutil
    monkeypatch.setattr(psutil, "pid_exists", lambda pid: pid == 99999)

    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.get("/tunnel/status")
        assert r.status_code == 200
        data = r.json()
        assert data["active"] is True
        assert data["url"] == "https://active-tunnel.serveo.net"
        assert data["pid"] == 99999


def test_tunnel_start_endpoint_waits_for_url_file(monkeypatch, tmp_path):
    """Verify POST /tunnel/start triggers background startup and awaits url file."""
    import asyncio
    from pathlib import Path
    from unittest.mock import AsyncMock
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    mnemo_dir = tmp_path / ".mnemostroma"
    mnemo_dir.mkdir(parents=True, exist_ok=True)
    url_file = mnemo_dir / "tunnel_url"

    # Mock subprocess call
    mock_exec = AsyncMock()
    monkeypatch.setattr("asyncio.create_subprocess_exec", mock_exec)

    # Mock asyncio.sleep to write the file on first call and delegate others
    original_sleep = asyncio.sleep
    async def mock_sleep(delay):
        if delay == 0.5:
            if not url_file.exists():
                url_file.write_text("https://new-started-tunnel.serveo.net", encoding="utf-8")
            await original_sleep(0.001)
        else:
            await original_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", mock_sleep)

    with TestClient(mcp_oauth_adapter.app) as client:
        r = client.post("/tunnel/start")
        assert r.status_code == 200
        data = r.json()
        assert data["started"] is True
        assert data["url"] == "https://new-started-tunnel.serveo.net"

    mock_exec.assert_called_once()



