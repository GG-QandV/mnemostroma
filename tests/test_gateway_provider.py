# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import os

import pytest
from starlette.testclient import TestClient

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest
from mnemostroma.gateway.dispatch import build_dispatch_plan
from mnemostroma.gateway.routes import create_app
from mnemostroma.gateway.routing import resolve_route

TEST_TOKEN = "sk-test-token-for-provider-tests"


@pytest.fixture
def disabled_client() -> TestClient:
    cfg = GatewayConfig(
        enabled=True,
        port=18900,
        token_env="TEST_PROVIDER_TOKEN",
        provider_mode="disabled",
    )
    os.environ["TEST_PROVIDER_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=cfg)
    yield TestClient(app)
    os.environ.pop("TEST_PROVIDER_TOKEN", None)


@pytest.fixture
def configured_client() -> TestClient:
    cfg = GatewayConfig(
        enabled=True,
        port=18901,
        token_env="TEST_PROVIDER_TOKEN",
        provider_mode="configured",
        provider_base_url="https://api.openai.com/v1",
        provider_token_env="OPENAI_API_KEY",
    )
    os.environ["TEST_PROVIDER_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=cfg)
    yield TestClient(app)
    os.environ.pop("TEST_PROVIDER_TOKEN", None)


VALID_PAYLOAD = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "hello"}],
}


class TestDispatchPlan:
    def test_disabled_provider_returns_not_dispatched(self):
        cfg = GatewayConfig(provider_mode="disabled")
        plan = build_dispatch_plan(cfg)
        assert plan.mode == "disabled"
        assert plan.would_dispatch is False
        assert plan.upstream_path is None

    def test_configured_provider_returns_blocked_without_network(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="OPENAI_KEY",
        )
        plan = build_dispatch_plan(cfg)
        assert plan.mode == "configured"
        assert plan.would_dispatch is True
        assert plan.upstream_path == "/v1/chat/completions"

    def test_disabled_route_execution_not_dispatched(self):
        cfg = GatewayConfig(provider_mode="disabled")
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        plan = resolve_route(req, cfg)
        assert plan.execution == "not_dispatched"

    def test_configured_route_execution_blocked(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="OPENAI_KEY",
        )
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        plan = resolve_route(req, cfg)
        assert plan.execution == "blocked"
        assert plan.reason == "provider_dispatch_not_enabled"

    def test_provider_plan_never_exposes_endpoint_or_token_env(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="OPENAI_KEY",
        )
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        plan = resolve_route(req, cfg)
        plan_str = str(plan.__dict__)
        assert "api.openai.com" not in plan_str
        assert "OPENAI_KEY" not in plan_str
        assert "provider_base_url" not in plan_str
        assert "provider_token_env" not in plan_str

    def test_configured_provider_does_not_read_environment(self):
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="SHOULD_NOT_BE_READ",
        )
        plan = build_dispatch_plan(cfg)
        assert plan.mode == "configured"


class TestProviderHTTP:
    def test_http_disabled_provider_plan(self, disabled_client: TestClient):
        resp = disabled_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        data = resp.json()
        assert data["execution"] == "not_dispatched"
        provider = data["provider"]
        assert provider["mode"] == "disabled"
        assert provider["would_dispatch"] is False

    def test_http_configured_provider_plan(self, configured_client: TestClient):
        resp = configured_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        data = resp.json()
        assert data["execution"] == "blocked"
        assert data["reason"] == "provider_dispatch_not_enabled"
        provider = data["provider"]
        assert provider["mode"] == "configured"
        assert provider["would_dispatch"] is True
        assert provider["upstream_path"] == "/v1/chat/completions"

    def test_http_configured_plan_does_not_expose_url_or_token(
        self, configured_client: TestClient
    ):
        resp = configured_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        body = resp.text
        assert "api.openai.com" not in body
        assert "OPENAI_API_KEY" not in body


class TestR5Purity:
    def test_r5_dispatch_does_not_import_httpx(self):
        import mnemostroma.gateway.dispatch as dispatch_mod
        with open(dispatch_mod.__file__) as f:
            src = f.read()
        assert "httpx" not in src

    def test_r5_dispatch_is_pure_sync(self):
        import inspect as _inspect

        from mnemostroma.gateway.dispatch import build_dispatch_plan as _b
        assert not _inspect.iscoroutinefunction(_b)
