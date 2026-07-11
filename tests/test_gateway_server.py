# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayStartupError
from mnemostroma.gateway.routes import create_app
from mnemostroma.gateway.server import GatewayServer

TEST_TOKEN = "test-token-value-123"


@pytest.fixture
def app():
    return create_app(TEST_TOKEN)


@pytest.fixture
def client(app):
    return TestClient(app)


class TestHealthz:
    def test_healthz_is_public_and_minimal(self, client):
        resp = client.get("/healthz")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "mnemo-gateway"
        assert "memory" not in data
        assert "version" not in data


class TestReadyz:
    def test_readyz_rejects_missing_bearer(self, client):
        resp = client.get("/readyz")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"

    def test_readyz_rejects_invalid_bearer(self, client):
        resp = client.get("/readyz", headers={"Authorization": "Bearer wrong-token"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "unauthorized"

    def test_readyz_accepts_valid_bearer(self, client):
        resp = client.get(
            "/readyz", headers={"Authorization": f"Bearer {TEST_TOKEN}"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["memory"] == "ready"

    def test_readyz_rejects_bearer_without_token(self, client):
        resp = client.get("/readyz", headers={"Authorization": "Bearer"})
        assert resp.status_code == 401


class TestGatewayInfo:
    def test_info_requires_auth(self, client):
        resp = client.get("/v1/gateway/info")
        assert resp.status_code == 401
        assert "version" not in resp.text

    def test_info_accepts_valid_auth(self, client):
        resp = client.get(
            "/v1/gateway/info",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "version" in data
        assert data["version"] == "0.1.0"
        assert "capabilities" in data
        assert "memory_mode" in data
        assert "endpoint" not in data
        assert "token" not in data
        assert "provider" not in data

    def test_info_hides_secrets_in_response(self, client):
        resp = client.get(
            "/v1/gateway/info",
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        text = resp.text.lower()
        assert "sk-" not in text
        assert TEST_TOKEN not in text


class TestUnknownRoute:
    def test_unknown_route_returns_json_404(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert data["error"]["code"] == "not_found"
        assert data["error"]["message"] == "not found"

    def test_unknown_route_does_not_require_auth(self, client):
        resp = client.get("/nonexistent")
        assert resp.status_code == 404


class TestUnauthorizedResponse:
    def test_unauthorized_payload_is_consistent(self, client):
        resp = client.get("/readyz")
        assert resp.headers.get("www-authenticate") == "Bearer"
        data = resp.json()
        assert data == {
            "error": {"code": "unauthorized", "message": "authentication required"}
        }

    def test_healthz_does_not_return_www_authenticate(self, client):
        resp = client.get("/healthz")
        assert resp.headers.get("www-authenticate") is None

    def test_info_rejects_improper_auth_scheme(self, client):
        resp = client.get(
            "/v1/gateway/info", headers={"Authorization": "Basic abc"}
        )
        assert resp.status_code == 401

    def test_readyz_rejects_empty_bearer(self, client):
        resp = client.get(
            "/readyz", headers={"Authorization": "Bearer "}
        )
        assert resp.status_code == 401


class TestServerLifecycle:
    @pytest.mark.asyncio
    async def test_gateway_binds_configured_loopback_port(self):
        cfg = GatewayConfig(enabled=True, port=18780, token_env="GATEWAY_TEST_TOKEN")
        os.environ["GATEWAY_TEST_TOKEN"] = TEST_TOKEN
        try:
            server = GatewayServer(cfg)
            await server.start()
            assert server.started is True

            resp = await _async_get("http://127.0.0.1:18780/healthz")
            assert resp == 200

            await server.stop()
            assert server.started is False
        finally:
            os.environ.pop("GATEWAY_TEST_TOKEN", None)

    @pytest.mark.asyncio
    async def test_gateway_stop_closes_listener(self):
        cfg = GatewayConfig(enabled=True, port=18781, token_env="GATEWAY_TEST_TOKEN2")
        os.environ["GATEWAY_TEST_TOKEN2"] = TEST_TOKEN
        try:
            server = GatewayServer(cfg)
            await server.start()
            assert server.started is True

            await server.stop()
            assert server.started is False

            cfg2 = GatewayConfig(
                enabled=True, port=18781, token_env="GATEWAY_TEST_TOKEN2"
            )
            server2 = GatewayServer(cfg2)
            await server2.start()
            assert server2.started is True
            await server2.stop()
        finally:
            os.environ.pop("GATEWAY_TEST_TOKEN2", None)

    @pytest.mark.asyncio
    async def test_gateway_disabled_does_not_bind(self):
        cfg = GatewayConfig(enabled=False, port=18782)
        server = GatewayServer(cfg)
        await server.start()
        assert server.started is False
        assert server.task is None

    @pytest.mark.asyncio
    async def test_gateway_port_conflict_fails_without_fallback(self):
        cfg1 = GatewayConfig(enabled=True, port=18783, token_env="GATEWAY_TEST_TOKEN3")
        cfg2 = GatewayConfig(enabled=True, port=18783, token_env="GATEWAY_TEST_TOKEN4")
        os.environ["GATEWAY_TEST_TOKEN3"] = TEST_TOKEN
        os.environ["GATEWAY_TEST_TOKEN4"] = TEST_TOKEN
        try:
            server1 = GatewayServer(cfg1)
            await server1.start()
            assert server1.started is True

            server2 = GatewayServer(cfg2)
            with pytest.raises(GatewayStartupError):
                await server2.start()

            await server1.stop()
        finally:
            os.environ.pop("GATEWAY_TEST_TOKEN3", None)
            os.environ.pop("GATEWAY_TEST_TOKEN4", None)


async def _async_get(url: str) -> int:
    import httpx
    async with httpx.AsyncClient() as client:
        resp = await client.get(url)
        return resp.status_code
