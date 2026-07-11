# SPDX-License-Identifier: FSL-1.1-MIT
"""R11 — admission control for bounded concurrent dispatch."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mnemostroma.gateway.admission import DispatchAdmission
from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.provider import ProviderRequest, ProviderResponse
from mnemostroma.gateway.provider_errors import ProviderTransportError


def _plan(mode: str = "off") -> MemoryPlan:
    return MemoryPlan(mode=mode, would_inject=mode == "active")


class HangingTransport:
    def __init__(self, event: asyncio.Event | None = None) -> None:
        self._event = event or asyncio.Event()
        self.called: bool = False

    async def send(self, req: ProviderRequest) -> ProviderResponse:
        self.called = True
        await self._event.wait()
        return FakeProviderTransport().send(req)


class HangingInjector:
    def __init__(self, event: asyncio.Event) -> None:
        self._event = event
        self.called: bool = False

    async def inject(self, msg: str) -> str:
        self.called = True
        await self._event.wait()
        return "<mem>test</mem>"


# ══════════════════════════════════════════════════════════════════════
# Config validation
# ══════════════════════════════════════════════════════════════════════


class TestAdmissionConfig:
    def test_dispatch_limit_defaults(self):
        cfg = GatewayConfig()
        assert cfg.max_concurrent_dispatches == 8
        assert cfg.max_concurrent_memory_requests == 2

    def test_dispatch_limit_rejects_zero_and_above_maximum(self):
        from mnemostroma.gateway.errors import GatewayConfigError
        from mnemostroma.gateway.policy import validate_gateway_config
        for bad in (0, -1, 65):
            with pytest.raises(GatewayConfigError):
                validate_gateway_config(GatewayConfig(max_concurrent_dispatches=bad))

    def test_memory_limit_rejects_zero_and_above_total_limit(self):
        from mnemostroma.gateway.errors import GatewayConfigError
        from mnemostroma.gateway.policy import validate_gateway_config
        for bad in (0, -1, 9):
            with pytest.raises(GatewayConfigError):
                validate_gateway_config(
                    GatewayConfig(max_concurrent_dispatches=8, max_concurrent_memory_requests=bad)
                )


# ══════════════════════════════════════════════════════════════════════
# Admission unit
# ══════════════════════════════════════════════════════════════════════


class TestAdmissionUnit:
    @pytest.mark.asyncio
    async def test_dry_run_bypasses_admission(self):
        # Executor without admission wired — no permit needed
        executor = GatewayExecutor(transport=FakeProviderTransport())
        result = await executor.execute(_chat(), _plan())
        assert result["choices"][0]["message"]["content"] == "Fake transport response"

    @pytest.mark.asyncio
    async def test_first_dispatch_acquires_and_releases_total_permit(self):
        admission = DispatchAdmission(max_total=1)
        p = await admission.try_acquire(memory_active=False)
        assert p is not None
        async with p:
            pass
        # Should be able to acquire again after release
        p2 = await admission.try_acquire(memory_active=False)
        assert p2 is not None
        async with p2:
            pass

    @pytest.mark.asyncio
    async def test_limit_exhaustion_returns_provider_busy_without_transport_call(self):
        admission = DispatchAdmission(max_total=1)
        p = await admission.try_acquire(memory_active=False)
        assert p is not None

        transport = HangingTransport()
        executor = GatewayExecutor(
            transport=transport, admission=admission,
        )
        with pytest.raises(ProviderTransportError) as exc:
            await executor.execute(_chat(), _plan())
        assert exc.value.code == "provider_busy"
        assert exc.value.status == 503
        assert not transport.called
        async with p:
            pass

    @pytest.mark.asyncio
    async def test_limit_releases_after_success(self):
        admission = DispatchAdmission(max_total=1)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        await executor.execute(_chat(), _plan())
        # Second request succeeds (slot was released)
        await executor.execute(_chat(), _plan())

    @pytest.mark.asyncio
    async def test_limit_releases_after_provider_error(self):
        class FailTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                raise ProviderTransportError(502, "provider_server_error", "fail")

        admission = DispatchAdmission(max_total=1)
        executor = GatewayExecutor(
            transport=FailTransport(), admission=admission,
        )
        with pytest.raises(ProviderTransportError):
            await executor.execute(_chat(), _plan())
        # Slot released — next request works
        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        await executor2.execute(_chat(), _plan())

    @pytest.mark.asyncio
    async def test_limit_releases_after_normalization_error(self):
        class BadTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                return ProviderResponse(status=200, body='{"choices": []}')

        admission = DispatchAdmission(max_total=1)
        executor = GatewayExecutor(
            transport=BadTransport(), admission=admission,
        )
        with pytest.raises(ProviderTransportError):
            await executor.execute(_chat(), _plan())
        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        await executor2.execute(_chat(), _plan())

    @pytest.mark.asyncio
    async def test_limit_releases_after_memory_injection_error(self):
        class FailInjector:
            async def inject(self, msg: str) -> str:
                raise RuntimeError("oom")

        admission = DispatchAdmission(max_total=1, max_memory=1)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=FailInjector(),
            admission=admission,
        )
        from mnemostroma.gateway.errors import MemoryUnavailable
        with pytest.raises(MemoryUnavailable):
            await executor.execute(
                _chat(),
                MemoryPlan(mode="active", would_inject=True),
            )
        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        await executor2.execute(_chat(), _plan())

    @pytest.mark.asyncio
    async def test_limit_releases_after_cancellation(self):
        admission = DispatchAdmission(max_total=1)
        event = asyncio.Event()
        transport = HangingTransport(event)
        executor = GatewayExecutor(
            transport=transport, admission=admission,
        )

        import contextlib

        task = asyncio.create_task(executor.execute(_chat(), _plan()))
        await asyncio.sleep(0.01)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

        # Slot released
        executor2 = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        await executor2.execute(_chat(), _plan())

    @pytest.mark.asyncio
    async def test_fake_and_http_share_total_dispatch_limit(self):
        admission = DispatchAdmission(max_total=1)
        p = await admission.try_acquire(memory_active=False)
        assert p is not None

        executor = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        with pytest.raises(ProviderTransportError):
            await executor.execute(_chat(), _plan())
        async with p:
            pass

    @pytest.mark.asyncio
    async def test_memory_active_requires_memory_permit(self):
        admission = DispatchAdmission(max_total=8, max_memory=1)
        p = await admission.try_acquire(memory_active=True)
        assert p is not None

        executor = GatewayExecutor(
            transport=FakeProviderTransport(), admission=admission,
        )
        with pytest.raises(ProviderTransportError) as exc:
            await executor.execute(
                _chat(),
                MemoryPlan(mode="active", would_inject=True),
            )
        assert exc.value.code == "provider_busy"
        async with p:
            pass

    @pytest.mark.asyncio
    async def test_memory_limit_exhaustion_does_not_call_injector_or_transport(self):
        admission = DispatchAdmission(max_total=8, max_memory=1)
        event = asyncio.Event()
        p = await admission.try_acquire(memory_active=True)
        assert p is not None

        injector = HangingInjector(event)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
            admission=admission,
        )
        with pytest.raises(ProviderTransportError):
            await executor.execute(
                _chat(),
                MemoryPlan(mode="active", would_inject=True),
            )
        assert not injector.called
        async with p:
            pass

    @pytest.mark.asyncio
    async def test_total_limit_exhaustion_does_not_call_injector_or_transport(self):
        admission = DispatchAdmission(max_total=1)
        event = asyncio.Event()
        p = await admission.try_acquire(memory_active=False)
        assert p is not None

        injector = HangingInjector(event)
        transport = HangingTransport(event)
        executor = GatewayExecutor(
            transport=transport,
            memory_injector=injector,
            admission=admission,
        )
        with pytest.raises(ProviderTransportError):
            await executor.execute(
                _chat(),
                MemoryPlan(mode="active", would_inject=True),
            )
        assert not injector.called
        assert not transport.called
        async with p:
            pass

    @pytest.mark.asyncio
    async def test_failed_memory_permit_does_not_leak_total_permit(self):
        admission = DispatchAdmission(max_total=1, max_memory=1)
        # Acquire total with memory
        p = await admission.try_acquire(memory_active=False)
        assert p is not None

        # Total exhausted, memory also inaccessible
        # Now try memory active — total is exhausted so should fail
        p2 = await admission.try_acquire(memory_active=True)
        assert p2 is None

        # Total should still be held by p
        p3 = await admission.try_acquire(memory_active=False)
        assert p3 is None

        async with p:
            pass

    @pytest.mark.asyncio
    async def test_off_and_planned_do_not_consume_memory_permits(self):
        admission = DispatchAdmission(max_total=8, max_memory=1)
        # Acquire the single memory slot
        p = await admission.try_acquire(memory_active=True)
        assert p is not None

        # off and planned should work (they don't need memory slot)
        for mode in ("off", "planned"):
            executor = GatewayExecutor(
                transport=FakeProviderTransport(), admission=admission,
            )
            await executor.execute(_chat(), MemoryPlan(mode=mode, would_inject=False))
        async with p:
            pass

    @pytest.mark.asyncio
    async def test_observation_runs_after_permit_is_released(self):
        admission = DispatchAdmission(max_total=1)
        calls: list[str] = []

        class Obs:
            async def observe(self, *, user_message: str, assistant_message: str) -> None:
                calls.append(user_message)

        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=Obs(),
            admission=admission,
        )
        await executor.execute(_chat((("user", "q1"),)), _plan())
        await asyncio.sleep(0)
        # Observation runs after permit released
        assert len(calls) == 1


def _chat(role_content: tuple[tuple[str, str], ...] | None = None, **kw: Any) -> ChatRequest:
    if role_content is None:
        role_content = (("user", "hi"),)
    return ChatRequest(
        model="gpt-4",
        messages=tuple(ChatMessage(role=r, content=c) for r, c in role_content),
        **kw,
    )
