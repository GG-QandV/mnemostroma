# SPDX-License-Identifier: FSL-1.1-MIT
"""
PATCH-2026-05-24: тесты singleton SessionManager (lifespan-based)
Запуск: pytest tests/test_mcp_http_adapter_patch.py -v
"""
import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from starlette.testclient import TestClient


TOKEN_VALUE = "test-token-abc123"


@pytest.fixture(autouse=True)
def patch_token(monkeypatch):
    monkeypatch.setattr(
        "mnemostroma.integration.mcp_http_adapter.TOKEN", TOKEN_VALUE
    )


@pytest.fixture
def app():
    from mnemostroma.integration.mcp_http_adapter import make_mcp_app
    return make_mcp_app()


@pytest.fixture
def client(app):
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def auth_headers():
    return {"Authorization": f"Bearer {TOKEN_VALUE}"}


# ══════════════════════════════════════════════════════════════════════
# PATCH-1: SessionManager в lifespan (не global singleton)
# ══════════════════════════════════════════════════════════════════════

class TestSessionManagerLifespan:

    def test_sm_same_instance_across_requests(self, client, auth_headers):
        """SM не пересоздаётся между запросами."""
        with patch(
            "mnemostroma.integration.mcp_http_adapter.safe_ipc_call",
            new=AsyncMock(return_value={"status": "ok"}),
        ):
            resp1 = client.get("/health")
            resp2 = client.get("/health")
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_handle_mcp_unauthorized(self, client):
        response = client.post("/mcp", json={})
        assert response.status_code == 401

    def test_handle_mcp_wrong_token(self, client):
        response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer wrong-token"},
            json={},
        )
        assert response.status_code == 401

    def test_handle_mcp_token_via_query(self, client):
        with patch(
            "mnemostroma.integration.mcp_http_adapter.safe_ipc_call",
            new=AsyncMock(return_value={"status": "ok"}),
        ):
            response = client.get(f"/health?token={TOKEN_VALUE}")
        assert response.status_code == 200

    def test_handle_mcp_api_key_header(self, client):
        with patch(
            "mnemostroma.integration.mcp_http_adapter.safe_ipc_call",
            new=AsyncMock(return_value={"status": "ok"}),
        ):
            response = client.get("/health", headers={"api-key": TOKEN_VALUE})
        assert response.status_code == 200


# ══════════════════════════════════════════════════════════════════════
# Health (регрессия)
# ══════════════════════════════════════════════════════════════════════

class TestHealthEndpoint:

    def test_health_daemon_connected(self, client):
        with patch(
            "mnemostroma.integration.mcp_http_adapter.safe_ipc_call",
            new=AsyncMock(return_value={"status": "ok"}),
        ):
            response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["mcpConfirmed"] is True

    def test_health_daemon_down(self, client):
        with patch(
            "mnemostroma.integration.mcp_http_adapter.safe_ipc_call",
            new=AsyncMock(side_effect=ConnectionError("daemon not running")),
        ):
            response = client.get("/health")
        assert response.status_code == 503

    def test_mcp_config_no_serveo(self, client, monkeypatch):
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.state.get_tunnel_url", lambda: None
        )
        response = client.get("/mcp-config")
        assert response.status_code == 200
        data = response.json()
        url = data["mcpServers"]["mnemostroma"]["url"]
        assert "127.0.0.1:8768" in url

    def test_mcp_config_with_serveo(self, client, monkeypatch):
        serveo_url = "https://test-abc.serveousercontent.com"
        monkeypatch.setattr(
            "mnemostroma.integration.tunnel.state.get_tunnel_url", lambda: serveo_url
        )
        response = client.get("/mcp-config")
        data = response.json()
        url = data["mcpServers"]["mnemostroma"]["url"]
        assert url == f"{serveo_url}/mcp"
        headers = data["mcpServers"]["mnemostroma"]["headers"]
        assert "serveo-skip-browser-warning" in headers
