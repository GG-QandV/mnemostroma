# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import json
import os

import httpx
import pytest

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
from mnemostroma.gateway.provider import ProviderRequest
from mnemostroma.gateway.provider_errors import ProviderTransportError

VALID_PAYLOAD = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "hello"}],
}


# ══════════════════════════════════════════════════════════════════════
# Transport — basic contract
# ══════════════════════════════════════════════════════════════════════


class TestHttpxTransportBasic:
    def test_http_dispatch_requires_provider_token(self):
        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="MISSING_VAR",
        )
        req = ProviderRequest(
            model="gpt-4",
            messages=({"role": "user", "content": "hi"},),
        )
        with pytest.raises(ProviderTransportError, match="credentials are unavailable"):
            import asyncio
            asyncio.run(transport.send(req))

    def test_missing_token_performs_no_network_call(self):
        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="MISSING_VAR",
        )
        req = ProviderRequest(
            model="gpt-4",
            messages=({"role": "user", "content": "hi"},),
        )
        with pytest.raises(ProviderTransportError):
            import asyncio
            asyncio.run(transport.send(req))

    @pytest.mark.asyncio
    async def test_http_transport_posts_expected_path(self):
        requests: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                200,
                json={
                    "id": "test",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "gpt-4",
                    "choices": [
                        {
                            "index": 0,
                            "message": {
                                "role": "assistant",
                                "content": "ok",
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-real-key"
        try:
            req = ProviderRequest(
                model="gpt-4",
                messages=({"role": "user", "content": "hi"},),
            )
            resp = await transport.send(req)
            assert resp.status == 200
            assert len(requests) == 1
            assert str(requests[0].url) == "https://api.openai.com/v1/chat/completions"
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_transport_sends_typed_nonstreaming_payload(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            assert body["model"] == "gpt-4"
            assert body["messages"] == [{"role": "user", "content": "hi"}]
            assert body["stream"] is False
            assert "tools" not in body
            assert "functions" not in body
            return httpx.Response(
                200,
                json={
                    "id": "test", "object": "chat.completion", "created": 1,
                    "model": "gpt-4",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-real-key"
        try:
            req = ProviderRequest(
                model="gpt-4",
                messages=({"role": "user", "content": "hi"},),
            )
            await transport.send(req)
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_transport_uses_provider_bearer_not_gateway_bearer(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            auth = request.headers.get("authorization", "")
            assert auth == "Bearer sk-provider-key"
            assert auth != "Bearer sk-gateway-token"
            return httpx.Response(
                200,
                json={
                    "id": "test", "object": "chat.completion", "created": 1,
                    "model": "gpt-4",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-provider-key"
        try:
            req = ProviderRequest(
                model="gpt-4",
                messages=({"role": "user", "content": "hi"},),
            )
            await transport.send(req)
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_transport_uses_normalized_base_url(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert str(request.url) == "https://api.openai.com/v1/chat/completions"
            return httpx.Response(
                200,
                json={
                    "id": "test", "object": "chat.completion", "created": 1,
                    "model": "gpt-4",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1/",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            await transport.send(req)
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)


# ══════════════════════════════════════════════════════════════════════
# Transport — error mapping
# ══════════════════════════════════════════════════════════════════════


class TestHttpxTransportErrors:
    @pytest.mark.asyncio
    async def test_http_timeout_maps_to_504(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("timeout")

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            with pytest.raises(ProviderTransportError) as exc:
                await transport.send(req)
            assert exc.value.status == 504
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_connect_error_maps_to_502(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            with pytest.raises(ProviderTransportError) as exc:
                await transport.send(req)
            assert exc.value.status == 502
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.parametrize("upstream_status,expected_code", [
        (401, "provider_auth_failed"),
        (403, "provider_auth_failed"),
        (429, "provider_rate_limited"),
        (400, "provider_rejected_request"),
        (404, "provider_rejected_request"),
        (422, "provider_rejected_request"),
        (500, "provider_server_error"),
        (502, "provider_server_error"),
        (503, "provider_server_error"),
    ])
    @pytest.mark.asyncio
    async def test_upstream_status_error_mapping(self, upstream_status, expected_code):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(upstream_status, text="upstream error")

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            with pytest.raises(ProviderTransportError) as exc:
                await transport.send(req)
            assert exc.value.code == expected_code
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_non_json_upstream_maps_to_provider_invalid_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="not json")

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            with pytest.raises(ProviderTransportError) as exc:
                await transport.send(req)
            assert exc.value.code == "provider_invalid_response"
            assert exc.value.status == 502
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_invalid_completion_shape_maps_to_provider_invalid_response(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={"id": "test", "object": "chat.completion", "choices": []},
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            with pytest.raises(ProviderTransportError) as exc:
                await transport.send(req)
            assert exc.value.code == "provider_invalid_response"
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_transport_performs_exactly_one_attempt(self):
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("refused")

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            with pytest.raises(ProviderTransportError):
                await transport.send(req)
            assert call_count == 1
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_transport_sends_internal_user_agent(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            ua = request.headers.get("user-agent", "")
            assert "mnemo" in ua.lower()
            return httpx.Response(
                200,
                json={
                    "id": "test", "object": "chat.completion", "created": 1,
                    "model": "gpt-4",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            await transport.send(req)
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)


# ══════════════════════════════════════════════════════════════════════
# Config validation
# ══════════════════════════════════════════════════════════════════════


class TestHttpDispatchConfig:
    def test_http_dispatch_requires_configured_provider(self):
        from mnemostroma.gateway.errors import GatewayConfigError
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(dispatch_mode="http", provider_mode="disabled")
        with pytest.raises(GatewayConfigError, match="provider_mode"):
            validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# HTTP dispatch integration
# ══════════════════════════════════════════════════════════════════════


class TestHttpDispatchIntegration:
    @pytest.mark.asyncio
    async def test_http_dispatch_returns_normalized_completion(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "chatcmpl_real", "object": "chat.completion", "created": 100,
                    "model": "gpt-4",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "real response"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            executor = GatewayExecutor(transport=transport)
            chat = ChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="hi")],
            )
            memory = MemoryPlan(mode="off", would_inject=False)
            result = await executor.execute(chat, memory)
            assert result["object"] == "chat.completion"
            assert result["choices"][0]["message"]["content"] == "real response"
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_dispatch_rejects_stream_true(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-key"
        try:
            executor = GatewayExecutor(transport=transport)
            chat = ChatRequest(
                model="gpt-4",
                messages=[ChatMessage(role="user", content="hi")],
                stream=True,
            )
            memory = MemoryPlan(mode="off", would_inject=False)
            from mnemostroma.gateway.errors import GatewayExecutionError
            with pytest.raises(GatewayExecutionError):
                await executor.execute(chat, memory)
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    @pytest.mark.asyncio
    async def test_http_transport_never_leaks_token_or_base_url(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "id": "test", "object": "chat.completion", "created": 1,
                    "model": "gpt-4",
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                },
            )

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_PROVIDER_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        os.environ["TEST_PROVIDER_KEY"] = "sk-leak-test-key"
        try:
            req = ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            resp = await transport.send(req)
            body = resp.body.lower()
            assert "api.openai.com" not in body
            assert "sk-leak-test-key" not in body
            assert "authorization" not in body
        finally:
            os.environ.pop("TEST_PROVIDER_KEY", None)

    def test_http_dispatch_never_calls_conductor_inject_or_observe(self):
        import mnemostroma.gateway.httpx_transport as mod
        with open(mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "observe" not in src.lower()
        assert "inject" not in src.lower()
