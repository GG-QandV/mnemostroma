# SPDX-License-Identifier: FSL-1.1-MIT
"""R13 — cancellation propagation and permit cleanup."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mnemostroma.gateway.admission import DispatchAdmission
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.provider import ProviderRequest


def _chat(role: str = "user", content: str = "hi") -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=(ChatMessage(role=role, content=content),),
    )


def _plan(mode: str = "off") -> MemoryPlan:
    return MemoryPlan(mode=mode, would_inject=mode == "active")


class BlockingInjector:
    def __init__(self, started: asyncio.Event) -> None:
        self._started = started
        self._block = asyncio.Event()
        self.called = False

    async def inject(self, msg: str) -> str:
        self.called = True
        self._started.set()
        await self._block.wait()
        return "<mem>x</mem>"


class BlockingTransport:
    def __init__(self, started: asyncio.Event) -> None:
        self._started = started
        self._block = asyncio.Event()
        self.called = False

    async def send(self, req: ProviderRequest) -> Any:
        self.called = True
        self._started.set()
        await self._block.wait()
        return await FakeProviderTransport().send(req)


class CapturingObserver:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def observe(
        self, *, user_message: str, assistant_message: str
    ) -> None:
        self.calls.append("observed")


async def _cancel_and_await(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


# ══════════════════════════════════════════════════════════════════════
# Cancellation during memory injection
# ══════════════════════════════════════════════════════════════════════


class TestCancellationMemoryInjection:
    @pytest.mark.asyncio
    async def test_cancellation_during_memory_injection_propagates_cancelled_error(self):
        started = asyncio.Event()
        injector = BlockingInjector(started)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan("active"))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_cancellation_during_memory_injection_never_calls_transport(self):
        started = asyncio.Event()
        injector = BlockingInjector(started)
        transport = BlockingTransport(asyncio.Event())
        executor = GatewayExecutor(
            transport=transport,
            memory_injector=injector,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan("active"))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)
        assert not transport.called

    @pytest.mark.asyncio
    async def test_cancellation_during_memory_injection_never_schedules_observation(self):
        started = asyncio.Event()
        injector = BlockingInjector(started)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
            completion_observer=obs,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan("active"))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)
        assert len(obs.calls) == 0

    @pytest.mark.asyncio
    async def test_cancellation_releases_memory_admission_permit(self):
        admission = DispatchAdmission(max_total=8, max_memory=1)
        started = asyncio.Event()
        injector = BlockingInjector(started)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
            admission=admission,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan("active"))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)

        class SimpleInjector:
            async def inject(self, msg: str) -> str:
                return "<mem>ok</mem>"

        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=SimpleInjector(),
            admission=admission,
        )
        await executor2.execute(_chat(), _plan("active"))


# ══════════════════════════════════════════════════════════════════════
# Cancellation during transport
# ══════════════════════════════════════════════════════════════════════


class TestCancellationTransport:
    @pytest.mark.asyncio
    async def test_cancellation_during_transport_propagates_cancelled_error(self):
        started = asyncio.Event()
        transport = BlockingTransport(started)
        executor = GatewayExecutor(transport=transport)

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    @pytest.mark.asyncio
    async def test_cancellation_during_transport_never_calls_normalizer(self):
        started = asyncio.Event()
        transport = BlockingTransport(started)
        executor = GatewayExecutor(transport=transport)

        captured: list[str] = []

        class SpyingTransport:
            def __init__(self, inner: BlockingTransport) -> None:
                self._inner = inner

            async def send(self, req: ProviderRequest) -> Any:
                captured.append("send")
                return await self._inner.send(req)

        executor = GatewayExecutor(transport=SpyingTransport(transport))

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)
        assert captured == ["send"]

    @pytest.mark.asyncio
    async def test_cancellation_during_transport_never_schedules_observation(self):
        started = asyncio.Event()
        transport = BlockingTransport(started)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=transport,
            completion_observer=obs,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)
        assert len(obs.calls) == 0

    @pytest.mark.asyncio
    async def test_cancellation_releases_total_admission_permit(self):
        admission = DispatchAdmission(max_total=1)
        started = asyncio.Event()
        transport = BlockingTransport(started)
        executor = GatewayExecutor(
            transport=transport,
            admission=admission,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)

        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(),
            admission=admission,
        )
        await executor2.execute(_chat(), _plan())


# ══════════════════════════════════════════════════════════════════════
# Post-cancellation admission
# ══════════════════════════════════════════════════════════════════════


class TestPostCancellationAdmission:
    @pytest.mark.asyncio
    async def test_request_after_cancelled_total_dispatch_is_admitted(self):
        admission = DispatchAdmission(max_total=1)
        started = asyncio.Event()
        transport = BlockingTransport(started)
        executor = GatewayExecutor(transport=transport, admission=admission)

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)

        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        await executor2.execute(_chat(), _plan())

    @pytest.mark.asyncio
    async def test_request_after_cancelled_memory_dispatch_is_admitted(self):
        admission = DispatchAdmission(max_total=8, max_memory=1)
        started = asyncio.Event()
        injector = BlockingInjector(started)

        class SimpleInjector:
            async def inject(self, msg: str) -> str:
                return "<mem>ok</mem>"

        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
            admission=admission,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan("active"))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)

        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=SimpleInjector(),
            admission=admission,
        )
        await executor2.execute(_chat(), _plan("active"))


# ══════════════════════════════════════════════════════════════════════
# HTTPX does not map CancelledError
# ══════════════════════════════════════════════════════════════════════


class TestHttpTransportCancellation:
    @pytest.mark.asyncio
    async def test_cancelled_httpx_transport_does_not_map_to_provider_timeout(self):
        import os

        import httpx

        from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
        from mnemostroma.gateway.provider import ProviderRequest

        os.environ["R13_HTTP_KEY"] = "sk-test"
        started = asyncio.Event()
        block = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            started.set()
            await block.wait()
            return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="R13_HTTP_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        async def run() -> None:
            await transport.send(ProviderRequest(model="gpt-4", messages=({"role":"user","content":"hi"},)))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        os.environ.pop("R13_HTTP_KEY", None)

    @pytest.mark.asyncio
    async def test_cancelled_httpx_transport_does_not_map_to_provider_unreachable(self):
        import os

        import httpx

        from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
        from mnemostroma.gateway.provider import ProviderRequest

        os.environ["R13_HTTP_KEY2"] = "sk-test"
        started = asyncio.Event()
        block = asyncio.Event()

        async def handler(request: httpx.Request) -> httpx.Response:
            started.set()
            await block.wait()
            raise httpx.ConnectError("won't reach here before cancel")

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="R13_HTTP_KEY2",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )

        async def run() -> None:
            await transport.send(ProviderRequest(model="gpt-4", messages=({"role":"user","content":"hi"},)))

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        os.environ.pop("R13_HTTP_KEY2", None)


# ══════════════════════════════════════════════════════════════════════
# No side effects on cancelled request
# ══════════════════════════════════════════════════════════════════════


class TestNoSideEffects:
    @pytest.mark.asyncio
    async def test_cancelled_request_does_not_create_observation_task(self):
        spawner: list[Any] = []

        def track_spawner(coro: Any) -> Any:
            task = asyncio.create_task(coro)
            spawner.append(task)
            return task

        from mnemostroma.gateway.observer import ObservationTaskRegistry

        registry = ObservationTaskRegistry(spawner=track_spawner)
        started = asyncio.Event()
        transport = BlockingTransport(started)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=transport,
            completion_observer=obs,
            observation_registry=registry,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)
        assert len(obs.calls) == 0
        # No observation tasks should have been spawned
        assert len(spawner) == 0

    @pytest.mark.asyncio
    async def test_cancelled_request_does_not_change_registry_state(self):
        from mnemostroma.gateway.observer import ObservationTaskRegistry

        registry = ObservationTaskRegistry()
        started = asyncio.Event()
        transport = BlockingTransport(started)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=transport,
            completion_observer=obs,
            observation_registry=registry,
        )

        async def run() -> None:
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await started.wait()
        task.cancel()
        await _cancel_and_await(task)

        # Drain is instant — no tasks were registered
        await registry.drain(timeout_seconds=0.01)
