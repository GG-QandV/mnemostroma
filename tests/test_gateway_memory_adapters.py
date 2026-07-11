# SPDX-License-Identifier: FSL-1.1-MIT
"""R14 — production memory adapter wiring."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import pytest
from starlette.testclient import TestClient

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import MemoryUnavailable
from mnemostroma.gateway.memory_injector import MemoryInjector
from mnemostroma.gateway.observer import CompletionObserver
from mnemostroma.integration.gateway_memory import (
    ConductorProxyCompletionObserver,
    ConductorProxyMemoryInjector,
    create_gateway_app,
)

_MEM_XML = "<memory><decisions>R14</decisions></memory>"
_TEST_TOKEN = "sk-r14-test-token"


@dataclass
class FakeMemoryBlock:
    context: str = _MEM_XML
    tools: list[dict[str, Any]] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


class FakeProxy:
    def __init__(self) -> None:
        self.inject_calls: list[str] = []
        self.observe_calls: list[tuple[str, str]] = []

    async def inject(
        self, user_message: str, **kw: Any
    ) -> FakeMemoryBlock:
        self.inject_calls.append(user_message)
        return FakeMemoryBlock(context=_MEM_XML)

    async def observe(
        self, user_message: str, assistant_message: str
    ) -> None:
        self.observe_calls.append((user_message, assistant_message))


class FailOnInjectProxy:
    async def inject(self, user_message: str, **kw: Any) -> Any:
        raise RuntimeError("proxy failure")


# ══════════════════════════════════════════════════════════════════════
# Injector adapter
# ══════════════════════════════════════════════════════════════════════


class TestMemoryInjectorAdapter:
    @pytest.mark.asyncio
    async def test_injector_adapter_satisfies_injector_protocol(self):
        adapter = ConductorProxyMemoryInjector(FakeProxy())
        # Structural subtyping: should be assignable to MemoryInjector
        _: MemoryInjector = adapter

    @pytest.mark.asyncio
    async def test_injector_adapter_returns_only_memory_xml_text(self):
        proxy = FakeProxy()
        adapter = ConductorProxyMemoryInjector(proxy)
        result = await adapter.inject("test message")
        assert result == _MEM_XML
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_injector_adapter_does_not_expose_block_metadata(self):
        class RichBlock:
            context: str = _MEM_XML
            tools: list = []
            stats: dict = {"scores": [0.9]}

        class RichProxy:
            async def inject(self, msg: str, **kw: Any) -> RichBlock:
                return RichBlock()

        adapter = ConductorProxyMemoryInjector(RichProxy())
        result = await adapter.inject("msg")
        assert result == _MEM_XML
        # Cannot access tools or stats from outside
        assert not hasattr(result, "tools")
        assert not hasattr(result, "stats")

    @pytest.mark.asyncio
    async def test_injector_adapter_propagates_cancellation(self):
        import asyncio

        entered = asyncio.Event()

        class BlockingProxy:
            async def inject(self, msg: str, **kw: Any) -> Any:
                entered.set()
                await asyncio.Event().wait()
                return FakeMemoryBlock()

        adapter = ConductorProxyMemoryInjector(BlockingProxy())

        async def run() -> None:
            await adapter.inject("hi")

        task = asyncio.create_task(run())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_injector_adapter_maps_proxy_failure_to_memory_unavailable(self):
        adapter = ConductorProxyMemoryInjector(FailOnInjectProxy())
        with pytest.raises(MemoryUnavailable):
            await adapter.inject("test")

    @pytest.mark.asyncio
    async def test_injector_adapter_passes_max_tokens(self):
        class RecordingProxy:
            def __init__(self) -> None:
                self.max_tokens: int | None = None

            async def inject(self, msg: str, **kw: Any) -> FakeMemoryBlock:
                self.max_tokens = kw.get("max_tokens")
                return FakeMemoryBlock()

        proxy = RecordingProxy()
        adapter = ConductorProxyMemoryInjector(proxy, max_tokens=450)
        await adapter.inject("hi")
        assert proxy.max_tokens == 450


# ══════════════════════════════════════════════════════════════════════
# Observer adapter
# ══════════════════════════════════════════════════════════════════════


class TestObserverAdapter:
    @pytest.mark.asyncio
    async def test_observer_adapter_satisfies_observer_protocol(self):
        adapter = ConductorProxyCompletionObserver(FakeProxy())
        _: CompletionObserver = adapter

    @pytest.mark.asyncio
    async def test_observer_adapter_forwards_exactly_two_strings_once(self):
        proxy = FakeProxy()
        adapter = ConductorProxyCompletionObserver(proxy)
        await adapter.observe(
            user_message="hello",
            assistant_message="world",
        )
        assert len(proxy.observe_calls) == 1
        user, asst = proxy.observe_calls[0]
        assert user == "hello"
        assert asst == "world"

    @pytest.mark.asyncio
    async def test_observer_adapter_does_not_forward_memory_or_provider_metadata(self):
        proxy = FakeProxy()
        adapter = ConductorProxyCompletionObserver(proxy)
        await adapter.observe(
            user_message="user text",
            assistant_message="assistant text",
        )
        args = proxy.observe_calls[0]
        assert "memory" not in args[0].lower()
        assert "memory" not in args[1].lower()
        assert "api.openai.com" not in args[0]
        assert "token" not in args[0].lower()

    @pytest.mark.asyncio
    async def test_observer_adapter_propagates_cancellation(self):
        import asyncio

        entered = asyncio.Event()

        class BlockingProxy:
            async def observe(self, user: str, asst: str) -> None:
                entered.set()
                await asyncio.Event().wait()

        adapter = ConductorProxyCompletionObserver(BlockingProxy())

        async def run() -> None:
            await adapter.observe(user_message="hi", assistant_message="ok")

        task = asyncio.create_task(run())
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_observer_adapter_propagates_non_cancellation_failure(self):
        class FailProxy:
            async def observe(self, user: str, asst: str) -> None:
                raise RuntimeError("observer fail")

        adapter = ConductorProxyCompletionObserver(FailProxy())
        with pytest.raises(RuntimeError):
            await adapter.observe(user_message="hi", assistant_message="ok")


# ══════════════════════════════════════════════════════════════════════
# Builder
# ══════════════════════════════════════════════════════════════════════


class TestAppBuilder:
    def _cfg(self, **kw: Any) -> GatewayConfig:
        return GatewayConfig(
            auth_mode="local_bearer",
            token_env="R14_TEST_TOKEN",
            **kw,
        )

    @pytest.fixture(autouse=True)
    def _env(self) -> Any:
        os.environ["R14_TEST_TOKEN"] = _TEST_TOKEN
        yield
        os.environ.pop("R14_TEST_TOKEN", None)

    def test_app_builder_wires_adapters_when_proxy_is_supplied(self):
        cfg = self._cfg()
        app = create_gateway_app(config=cfg, proxy=FakeProxy())
        assert app.state.memory_injector is not None
        assert app.state.completion_observer is not None

    def test_app_builder_uses_no_memory_adapters_without_proxy(self):
        cfg = self._cfg()
        app = create_gateway_app(config=cfg, proxy=None)
        assert app.state.memory_injector is None
        assert app.state.completion_observer is None

    def test_active_memory_without_proxy_returns_503_before_transport(self):
        cfg = self._cfg(
            dispatch_mode="fake",
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="R14_PROV_TOKEN",
            memory_mode="active",
        )
        os.environ["R14_PROV_TOKEN"] = "sk-prov"
        app = create_gateway_app(config=cfg, proxy=None)
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["error"]["code"] == "memory_unavailable"
        os.environ.pop("R14_PROV_TOKEN", None)

    def test_observation_without_proxy_is_not_scheduled(self):
        cfg = self._cfg(
            dispatch_mode="fake",
            provider_mode="configured",
            provider_base_url="https://api.openai.com/v1",
            provider_token_env="R14_OBS_TOKEN",
            observation_mode="active",
        )
        os.environ["R14_OBS_TOKEN"] = "sk-obs"
        app = create_gateway_app(config=cfg, proxy=None)
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "gpt-4", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": f"Bearer {_TEST_TOKEN}"},
        )
        # Without observer, completion still works (best-effort observation is skipped)
        assert resp.status_code == 200
        os.environ.pop("R14_OBS_TOKEN", None)


# ══════════════════════════════════════════════════════════════════════
# Gateway does not import Conductor
# ══════════════════════════════════════════════════════════════════════


class TestNoConductorImport:
    def test_gateway_package_does_not_import_conductor_or_proxy(self):
        import mnemostroma.gateway.routes as mod
        with open(mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "conductor" not in src.lower()
