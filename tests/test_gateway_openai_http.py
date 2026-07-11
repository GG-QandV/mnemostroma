# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.routes import create_app

TEST_TOKEN = "sk-test-token-for-http-tests"


@pytest.fixture
def app_cfg() -> GatewayConfig:
    return GatewayConfig(
        enabled=True,
        port=18799,
        token_env="TEST_GATEWAY_HTTP_TOKEN",
    )


@pytest.fixture
def client(app_cfg: GatewayConfig) -> TestClient:
    os.environ["TEST_GATEWAY_HTTP_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=app_cfg)
    yield TestClient(app)
    os.environ.pop("TEST_GATEWAY_HTTP_TOKEN", None)


VALID_PAYLOAD = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "hello"}],
}


class TestChatCompletionsHTTP:
    def test_http_chat_completions_returns_authenticated_dry_run_plan(
        self, client: TestClient
    ):
        resp = client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "mnemo.gateway.route_plan"
        assert data["dry_run"] is True
        assert data["execution"] == "not_dispatched"
        assert data["memory"]["would_inject"] is False
        assert data["memory"]["would_observe"] is False
        assert data["id"].startswith("gwplan_")

    def test_http_chat_completions_rejects_missing_bearer(self, client: TestClient):
        resp = client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["error"]["code"] == "unauthorized"

    def test_http_chat_completions_rejects_invalid_json(self, client: TestClient):
        resp = client.post(
            "/v1/chat/completions",
            content=b"not json at all",
            headers={
                "Authorization": f"Bearer {TEST_TOKEN}",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_json"

    def test_http_chat_completions_ignores_unsupported_tools(self, client: TestClient):
        payload = {
            **VALID_PAYLOAD,
            "tools": [{"type": "function", "function": {"name": "foo"}}],
        }
        resp = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "mnemo.gateway.route_plan"

    def test_http_chat_completions_stream_true_rejected(self, client: TestClient):
        payload = {**VALID_PAYLOAD, "stream": True}
        resp = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["error"]["code"] == "invalid_request"

    def test_http_chat_completions_error_envelope_format(self, client: TestClient):
        resp = client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": "Bearer wrong-token"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert "error" in data
        assert "code" in data["error"]
        assert "message" in data["error"]

    def test_http_chat_completions_token_not_in_response(self, client: TestClient):
        resp = client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        body = resp.text
        assert TEST_TOKEN not in body
        assert "sk-test" not in body

    def test_http_chat_completions_ignores_unsupported_functions(
        self, client: TestClient
    ):
        payload = {
            **VALID_PAYLOAD,
            "functions": [{"name": "foo", "description": "bar"}],
        }
        resp = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "mnemo.gateway.route_plan"

    def test_http_chat_completions_ignores_unsupported_response_format(
        self, client: TestClient
    ):
        payload = {**VALID_PAYLOAD, "response_format": {"type": "json_object"}}
        resp = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "mnemo.gateway.route_plan"

    def test_http_chat_completions_passes_max_tokens(self, client: TestClient):
        payload = {**VALID_PAYLOAD, "max_tokens": 500}
        resp = client.post(
            "/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "mnemo.gateway.route_plan"


@pytest.fixture
def memory_client() -> TestClient:
    cfg = GatewayConfig(
        enabled=True,
        port=18800,
        token_env="TEST_GATEWAY_HTTP_TOKEN",
        memory_mode="planned",
    )
    os.environ["TEST_GATEWAY_HTTP_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=cfg)
    yield TestClient(app)
    os.environ.pop("TEST_GATEWAY_HTTP_TOKEN", None)


class TestMemoryHTTP:
    def test_http_memory_off_is_default(self, client: TestClient):
        resp = client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        data = resp.json()
        assert data["memory"]["mode"] == "off"
        assert data["memory"]["would_inject"] is False
        assert data["memory"]["source_message_index"] is None
        assert data["memory"]["max_tokens"] is None

    def test_http_memory_planned_returns_metadata_only(
        self, memory_client: TestClient
    ):
        resp = memory_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        data = resp.json()
        memory = data["memory"]
        assert memory["mode"] == "planned"
        assert memory["would_inject"] is True
        assert memory["would_observe"] is False
        assert isinstance(memory["source_message_index"], int)
        assert isinstance(memory["max_tokens"], int)
        body = resp.text
        assert "hello" not in body
