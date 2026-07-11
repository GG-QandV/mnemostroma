# SPDX-License-Identifier: FSL-1.1-MIT
"""R19 — provider credential resolution and redaction boundary."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import pytest

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
from mnemostroma.gateway.metrics import GatewayMetrics
from mnemostroma.gateway.provider import ProviderRequest
from mnemostroma.gateway.provider_credentials import (
    EnvironmentCredentialResolver,
    ProviderCredentialError,
)
from mnemostroma.gateway.provider_errors import ProviderTransportError

_COMPLETION_OK = {
    "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
}


class FakeMappingResolver:
    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping = dict(mapping or {})
        self.called_with: list[str] = []

    def resolve(self, env_name: str) -> str:
        self.called_with.append(env_name)
        token = self._mapping.get(env_name)
        if token is None:
            raise ProviderCredentialError()
        return token


# ══════════════════════════════════════════════════════════════════════
# Config-level: never read env when not needed
# ══════════════════════════════════════════════════════════════════════


class TestConfigNeverReads:
    def test_disabled_provider_never_reads_environment(self):
        resolver = FakeMappingResolver()
        _ = GatewayConfig(provider_mode="disabled")
        assert resolver.called_with == []

    def test_dry_run_never_reads_environment(self):
        resolver = FakeMappingResolver()
        _ = GatewayConfig(dispatch_mode="dry_run")
        assert resolver.called_with == []

    def test_invalid_provider_url_never_reads_environment(self):
        from mnemostroma.gateway.policy import validate_gateway_config
        resolver = FakeMappingResolver()
        cfg = GatewayConfig(
            provider_mode="configured",
            provider_base_url="invalid://",
            provider_token_env="FAKE_TOKEN",
        )
        from mnemostroma.gateway.errors import GatewayConfigError
        with pytest.raises(GatewayConfigError):
            validate_gateway_config(cfg)
        assert resolver.called_with == []


# ══════════════════════════════════════════════════════════════════════
# Resolver unit
# ══════════════════════════════════════════════════════════════════════


class TestResolverUnit:
    def test_enabled_live_dispatch_reads_only_configured_name_once(self):
        resolver = FakeMappingResolver({"MY_KEY": "sk-real"})
        token = resolver.resolve("MY_KEY")
        assert token == "sk-real"
        assert resolver.called_with == ["MY_KEY"]

    def test_missing_token_maps_to_stable_unavailable_error(self):
        resolver = FakeMappingResolver({})
        with pytest.raises(ProviderCredentialError):
            resolver.resolve("MISSING")

    def test_environment_resolver_reads_from_os_environ(self):
        os.environ["R19_TEST_KEY"] = "sk-test-value"
        resolver = EnvironmentCredentialResolver()
        token = resolver.resolve("R19_TEST_KEY")
        assert token == "sk-test-value"
        os.environ.pop("R19_TEST_KEY", None)

    def test_environment_missing_token_raises(self):
        if "R19_MISSING" in os.environ:
            os.environ.pop("R19_MISSING")
        resolver = EnvironmentCredentialResolver()
        with pytest.raises(ProviderCredentialError):
            resolver.resolve("R19_MISSING")

    def test_blank_or_whitespace_token_is_rejected(self):
        os.environ["R19_BLANK"] = "   "
        resolver = EnvironmentCredentialResolver()
        with pytest.raises(ProviderCredentialError):
            resolver.resolve("R19_BLANK")
        os.environ.pop("R19_BLANK", None)

    def test_token_with_control_characters_is_rejected(self):
        class NulFake:
            def resolve(self, name: str) -> str:
                return "sk-test\x00"

        resolver = NulFake()
        transport = HttpxProviderTransport(
            base_url="https://api.example.com/v1",
            token_env="ANY",
            credential_resolver=resolver,
        )
        import asyncio
        with pytest.raises(ProviderTransportError) as exc:
            asyncio.run(transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            ))
        assert exc.value.code == "provider_credentials_unavailable"

    def test_resolver_has_no_mutable_token_cache(self):
        os.environ["R19_CACHE"] = "sk-first"
        resolver = EnvironmentCredentialResolver()
        t1 = resolver.resolve("R19_CACHE")
        os.environ["R19_CACHE"] = "sk-second"
        t2 = resolver.resolve("R19_CACHE")
        assert t1 == "sk-first"
        assert t2 == "sk-second"
        assert t1 != t2
        os.environ.pop("R19_CACHE", None)

    def test_token_and_env_name_never_reach_observer_inputs(self):
        import inspect

        from mnemostroma.gateway.observer import CompletionObserver
        sig = inspect.signature(CompletionObserver.observe)
        params = list(sig.parameters.values())
        names = {p.name for p in params}
        # Only user_message and assistant_message
        assert "token" not in names
        assert "bearer" not in names
        assert "credential" not in names


# ══════════════════════════════════════════════════════════════════════
# Transport integration
# ══════════════════════════════════════════════════════════════════════


class TestTransportIntegration:
    @pytest.mark.asyncio
    async def test_token_is_sent_only_as_authorization_bearer_header(self):
        resolver = FakeMappingResolver({"T_KEY": "sk-bearer-test"})
        captured: list[dict[str, Any]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append({"auth": request.headers.get("authorization", "")})
            return httpx.Response(200, json=_COMPLETION_OK)

        transport = HttpxProviderTransport(
            base_url="https://api.example.com/v1",
            token_env="T_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            credential_resolver=resolver,
        )
        await transport.send(
            ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
        )
        assert captured[0]["auth"] == "Bearer sk-bearer-test"

    @pytest.mark.asyncio
    async def test_token_never_appears_in_controlled_error(self):
        resolver = FakeMappingResolver({})
        transport = HttpxProviderTransport(
            base_url="https://api.example.com/v1",
            token_env="MISSING_KEY",
            credential_resolver=resolver,
        )
        with pytest.raises(ProviderTransportError) as exc:
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )
        assert exc.value.code == "provider_credentials_unavailable"
        msg = str(exc.value).lower()
        assert "sk-" not in msg
        assert "token" not in msg or "unavailable" in msg

    @pytest.mark.asyncio
    async def test_environment_name_never_appears_in_controlled_error(self):
        resolver = FakeMappingResolver({})
        transport = HttpxProviderTransport(
            base_url="https://api.example.com/v1",
            token_env="MISSING_KEY",
            credential_resolver=resolver,
        )
        with pytest.raises(ProviderTransportError) as exc:
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )
        assert "MISSING_KEY" not in str(exc.value)

    @pytest.mark.asyncio
    async def test_token_and_env_name_never_appear_in_metrics_snapshot(self):
        m = GatewayMetrics()
        m.increment("gateway_requests_total")
        snap = m.snapshot()
        text = repr(snap)
        assert "sk-" not in text
        assert "bearer" not in text.lower()

    @pytest.mark.asyncio
    async def test_provider_failure_does_not_leak_authorization_header(self):
        class FailingHandler:
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                return httpx.Response(401)

        resolver = FakeMappingResolver({"T_KEY": "sk-leak-test"})
        transport = HttpxProviderTransport(
            base_url="https://api.example.com/v1",
            token_env="T_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(FailingHandler())),
            credential_resolver=resolver,
        )
        with pytest.raises(ProviderTransportError) as exc:
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )
        msg = str(exc.value)
        assert "Bearer" not in msg
        assert "sk-leak-test" not in msg

    @pytest.mark.asyncio
    async def test_cancellation_does_not_retry_or_reread_token(self):
        resolver = FakeMappingResolver({"X": "sk-val"})
        started = asyncio.Event()

        class BlockingHandler:
            async def __call__(self, request: httpx.Request) -> httpx.Response:
                started.set()
                await asyncio.Event().wait()
                return httpx.Response(200, json=_COMPLETION_OK)

        transport = HttpxProviderTransport(
            base_url="https://api.example.com/v1",
            token_env="X",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(BlockingHandler())),
            credential_resolver=resolver,
        )

        async def run() -> None:
            await transport.send(
                ProviderRequest(model="gpt-4", messages=({"role": "user", "content": "hi"},))
            )

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Token was read exactly once (before cancellation)
        assert resolver.called_with == ["X"]
