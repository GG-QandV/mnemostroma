# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import inspect
import os

import pytest
from starlette.testclient import TestClient

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.materialize import materialize_provider_request
from mnemostroma.gateway.provider import (
    ProviderRequest,
    ProviderResponse,
    ProviderTransport,
)
from mnemostroma.gateway.routes import create_app

TEST_TOKEN = "sk-test-token-for-fake-dispatch"

VALID_PAYLOAD = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "hello"}],
}


@pytest.fixture
def client() -> TestClient:
    cfg = GatewayConfig(
        enabled=True,
        port=19002,
        token_env="TEST_DEFAULT_TOKEN",
    )
    os.environ["TEST_DEFAULT_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=cfg)
    yield TestClient(app)
    os.environ.pop("TEST_DEFAULT_TOKEN", None)


# ══════════════════════════════════════════════════════════════════════
# Dispatch mode config
# ══════════════════════════════════════════════════════════════════════


class TestDispatchModeConfig:
    def test_dispatch_mode_defaults_to_dry_run(self):
        cfg = GatewayConfig()
        assert cfg.dispatch_mode == "dry_run"

    def test_dispatch_mode_rejects_unknown_value(self):
        from mnemostroma.gateway.errors import GatewayConfigError
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(
            dispatch_mode="invalid",
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="OPENAI_KEY",
        )
        with pytest.raises(GatewayConfigError, match="dispatch_mode"):
            validate_gateway_config(cfg)

    def test_fake_dispatch_requires_configured_provider(self):
        from mnemostroma.gateway.errors import GatewayConfigError
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(dispatch_mode="fake", provider_mode="disabled")
        with pytest.raises(GatewayConfigError, match="provider_mode"):
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Dry-run preserves route plan
# ══════════════════════════════════════════════════════════════════════


class TestDryRun:
    def test_dry_run_preserves_route_plan_response(self, client: TestClient):
        resp = client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        data = resp.json()
        assert data["object"] == "mnemo.gateway.route_plan"
        assert data["dry_run"] is True
        assert data["execution"] == "not_dispatched"


# ══════════════════════════════════════════════════════════════════════
# Materialization
# ══════════════════════════════════════════════════════════════════════


class TestMaterialization:
    def test_fake_dispatch_materializes_model_and_messages(self):
        chat = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
            stream=False,
        )
        memory = MemoryPlan(mode="off", would_inject=False)
        req = materialize_provider_request(chat, memory)
        assert req.model == "gpt-4"
        assert len(req.messages) == 1
        assert req.messages[0]["role"] == "user"
        assert req.messages[0]["content"] == "hello"
        assert req.stream is False

    def test_fake_dispatch_materializes_temperature_and_max_tokens(self):
        chat = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
            temperature=0.7,
            max_tokens=200,
        )
        memory = MemoryPlan(mode="off", would_inject=False)
        req = materialize_provider_request(chat, memory)
        assert req.temperature == 0.7
        assert req.max_tokens == 200

    def test_fake_dispatch_preserves_message_order(self):
        chat = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="user", content="first"),
                ChatMessage(role="assistant", content="ok"),
                ChatMessage(role="user", content="second"),
            ],
        )
        memory = MemoryPlan(mode="off", would_inject=False)
        req = materialize_provider_request(chat, memory)
        assert [m["role"] for m in req.messages] == [
            "system", "user", "assistant", "user",
        ]
        assert [m["content"] for m in req.messages] == [
            "be helpful", "first", "ok", "second",
        ]

    def test_fake_dispatch_never_materializes_memory_text(self):
        chat = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="my secret")],
        )
        memory = MemoryPlan(mode="planned", would_inject=True,
                            source_message_index=0, max_tokens=600)
        req = materialize_provider_request(chat, memory)
        assert req.memory_injection == "not_materialized"
        assert "my secret" not in str(req.memory_injection)


# ══════════════════════════════════════════════════════════════════════
# Fake transport
# ══════════════════════════════════════════════════════════════════════


class TestFakeTransport:
    @pytest.mark.asyncio
    async def test_fake_transport_is_deterministic(self):
        transport = FakeProviderTransport()
        req = ProviderRequest(
            model="gpt-4",
            messages=({"role": "user", "content": "hello"},),
        )
        resp1 = await transport.send(req)
        resp2 = await transport.send(req)
        assert resp1.body == resp2.body
        assert resp1.status == resp2.status

    @pytest.mark.asyncio
    async def test_fake_transport_returns_openai_completion_envelope(self):
        transport = FakeProviderTransport()
        req = ProviderRequest(
            model="claude-3",
            messages=({"role": "user", "content": "hi"},),
        )
        resp = await transport.send(req)
        assert resp.status == 200
        body = resp.body
        import json
        data = json.loads(body)
        assert data["object"] == "chat.completion"
        assert data["model"] == "claude-3"
        assert len(data["choices"]) == 1
        assert data["choices"][0]["message"]["role"] == "assistant"
        assert data["choices"][0]["finish_reason"] == "stop"
        assert "usage" in data


# ══════════════════════════════════════════════════════════════════════
# Execution
# ══════════════════════════════════════════════════════════════════════


class TestExecution:
    @pytest.mark.asyncio
    async def test_fake_dispatch_invokes_injected_transport_once(self):
        from mnemostroma.gateway.execution import GatewayExecutor
        calls = []

        class CountingTransport(ProviderTransport):
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                calls.append(req.model)
                return ProviderResponse(
                    status=200,
                    body='{"id":"test","object":"chat.completion",'
                         '"created":1,"model":"x","choices":['
                         '{"index":0,"message":{"role":"assistant",'
                         '"content":"ok"},"finish_reason":"stop"}],'
                         '"usage":{"prompt_tokens":0,"completion_tokens":0,'
                         '"total_tokens":0}}',
                )

        executor = GatewayExecutor(CountingTransport())
        chat = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        memory = MemoryPlan(mode="off", would_inject=False)
        result = await executor.execute(chat, memory)
        assert len(calls) == 1
        assert calls[0] == "gpt-4"
        assert result["object"] == "chat.completion"

    @pytest.mark.asyncio
    async def test_fake_dispatch_rejects_stream_true(self):
        from mnemostroma.gateway.execution import GatewayExecutionError, GatewayExecutor
        executor = GatewayExecutor(FakeProviderTransport())
        chat = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        memory = MemoryPlan(mode="off", would_inject=False)
        with pytest.raises(GatewayExecutionError, match="stream"):
            await executor.execute(chat, memory)


# ══════════════════════════════════════════════════════════════════════
# HTTP integration
# ══════════════════════════════════════════════════════════════════════


@pytest.fixture
def fake_client() -> TestClient:
    cfg = GatewayConfig(
        enabled=True,
        port=19000,
        token_env="TEST_FAKE_TOKEN",
        provider_mode="configured",
        provider_base_url="https://api.openai.com/v1",
        provider_token_env="OPENAI_API_KEY",
        dispatch_mode="fake",
    )
    os.environ["TEST_FAKE_TOKEN"] = TEST_TOKEN
    app = create_app(TEST_TOKEN, gateway_config=cfg)
    yield TestClient(app)
    os.environ.pop("TEST_FAKE_TOKEN", None)


class TestFakeDispatchHTTP:
    def test_http_fake_dispatch_returns_completion(self, fake_client: TestClient):
        resp = fake_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["object"] == "chat.completion"
        assert "choices" in data
        assert data["choices"][0]["message"]["role"] == "assistant"

    def test_http_fake_dispatch_does_not_return_route_plan(
        self, fake_client: TestClient
    ):
        resp = fake_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        data = resp.json()
        assert "dry_run" not in data
        assert "execution" not in data
        assert "memory" not in data
        assert "provider" not in data

    def test_http_fake_dispatch_rejects_stream_true(
        self, fake_client: TestClient
    ):
        resp = fake_client.post(
            "/v1/chat/completions",
            json={**VALID_PAYLOAD, "stream": True},
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "invalid_request" in data.get("error", {}).get("code", "")


# ══════════════════════════════════════════════════════════════════════
# Purity / isolation
# ══════════════════════════════════════════════════════════════════════


class TestIsolation:
    def test_fake_dispatch_does_not_read_provider_token_env(
        self, fake_client: TestClient
    ):
        os.environ.pop("OPENAI_API_KEY", None)
        resp = fake_client.post(
            "/v1/chat/completions",
            json=VALID_PAYLOAD,
            headers={"Authorization": f"Bearer {TEST_TOKEN}"},
        )
        assert resp.status_code == 200

    def test_fake_dispatch_does_not_import_httpx(self):
        import mnemostroma.gateway.fake_transport as ft_mod
        with open(ft_mod.__file__) as f:
            src = f.read()
        assert "httpx" not in src

    def test_fake_dispatch_not_import_httpx_in_materialize(self):
        import mnemostroma.gateway.materialize as mat_mod
        with open(mat_mod.__file__) as f:
            src = f.read()
        assert "httpx" not in src

    def test_execution_does_not_call_conductor_inject(self):
        import mnemostroma.gateway.execution as exec_mod
        with open(exec_mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "conductor" not in src.lower()

    def test_execution_does_not_call_conductor_observe(self):
        import mnemostroma.gateway.execution as exec_mod
        with open(exec_mod.__file__) as f:
            src = f.read()
        assert "observeuser" not in src.lower()
        assert "Conductor" not in src

    def test_materialize_is_pure_sync(self):
        assert not inspect.iscoroutinefunction(materialize_provider_request)
