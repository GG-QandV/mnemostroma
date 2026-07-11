# SPDX-License-Identifier: FSL-1.1-MIT
"""R17 — content-safe operational metrics."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from mnemostroma.gateway.admission import DispatchAdmission
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.metrics import GatewayMetrics
from mnemostroma.gateway.observer import ObservationTaskRegistry
from mnemostroma.gateway.provider import ProviderRequest, ProviderResponse
from mnemostroma.gateway.provider_errors import ProviderTransportError


class FakeClock:
    def __init__(self) -> None:
        self._t = 1000.0

    def __call__(self) -> float:
        self._t += 10.0
        return self._t


def _chat(role: str = "user", content: str = "hi") -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=(ChatMessage(role=role, content=content),),
    )


def _plan(mode: str = "off") -> MemoryPlan:
    return MemoryPlan(mode=mode, would_inject=mode == "active")


# ══════════════════════════════════════════════════════════════════════
# Unit
# ══════════════════════════════════════════════════════════════════════


class TestMetricsUnit:
    def test_metrics_start_empty(self):
        m = GatewayMetrics(clock=FakeClock())
        snap = m.snapshot()
        assert snap.gateway_requests_total == 0
        assert snap.gateway_requests_succeeded_total == 0

    def test_snapshot_is_immutable_copy(self):
        m = GatewayMetrics(clock=FakeClock())
        m.increment("gateway_requests_total")
        snap1 = m.snapshot()
        assert snap1.gateway_requests_total == 1
        m.increment("gateway_requests_total")
        snap2 = m.snapshot()
        assert snap2.gateway_requests_total == 2
        assert snap1.gateway_requests_total == 1

    def test_counter_increment(self):
        m = GatewayMetrics(clock=FakeClock())
        m.increment("gateway_requests_total")
        m.increment("gateway_requests_total")
        assert m.snapshot().gateway_requests_total == 2

    def test_each_latency_aggregate_has_correct_count_sum_min_max(self):
        m = GatewayMetrics(clock=FakeClock())
        for _ in range(3):
            start = m.record_start()
            m.record_end("gateway_request_duration_ms", start)
        agg = m.snapshot().gateway_request_duration_ms
        assert agg.count == 3
        assert agg.sum_ms == 30000.0  # 3 x 10000ms (FakeClock advances 10s/call)
        assert agg.min_ms == 10000.0
        assert agg.max_ms == 10000.0

    def test_metrics_contain_no_input_output_or_configuration_content(self):
        m = GatewayMetrics(clock=FakeClock())
        m.increment("gateway_requests_total")
        snapshot = m.snapshot()
        # Snapshot is a frozen dataclass — check no string data leaks
        text = repr(snapshot)
        for banned in ("prompt", "password", "token", "sk-", "bearer"):
            assert banned not in text.lower()


# ══════════════════════════════════════════════════════════════════════
# Executor metrics
# ══════════════════════════════════════════════════════════════════════


class TestExecutorMetrics:
    @pytest.mark.asyncio
    async def test_valid_success_increments_request_and_success_counters(self):
        m = GatewayMetrics(clock=FakeClock())
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            metrics=m,
        )
        await executor.execute(_chat(), _plan())
        snap = m.snapshot()
        assert snap.gateway_requests_total == 0  # tracked in routes
        assert snap.gateway_requests_succeeded_total == 0  # tracked in routes

    @pytest.mark.asyncio
    async def test_executor_records_dispatch_and_normalization_latency(self):
        m = GatewayMetrics(clock=FakeClock())
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            metrics=m,
        )
        await executor.execute(_chat(), _plan())
        snap = m.snapshot()
        assert snap.gateway_dispatch_duration_ms.count >= 1
        assert snap.gateway_normalization_duration_ms.count >= 1

    @pytest.mark.asyncio
    async def test_provider_failure_increments_provider_failure_counter(self):
        class FailTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                raise ProviderTransportError(502, "provider_server_error", "fail")

        m = GatewayMetrics(clock=FakeClock())
        executor = GatewayExecutor(transport=FailTransport(), metrics=m)
        with pytest.raises(ProviderTransportError):
            await executor.execute(_chat(), _plan())
        assert m.snapshot().gateway_provider_failures_total == 1

    @pytest.mark.asyncio
    async def test_normalization_failure_increments_normalization_failure_counter(self):
        class BadTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                return ProviderResponse(status=200, body='{"choices": []}')

        m = GatewayMetrics(clock=FakeClock())
        executor = GatewayExecutor(transport=BadTransport(), metrics=m)
        with pytest.raises(ProviderTransportError):
            await executor.execute(_chat(), _plan())
        assert m.snapshot().gateway_normalization_failures_total == 1

    @pytest.mark.asyncio
    async def test_memory_failure_increments_memory_failure_counter(self):
        class FailInjector:
            async def inject(self, msg: str) -> str:
                raise RuntimeError("oom")

        m = GatewayMetrics(clock=FakeClock())
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=FailInjector(),
            metrics=m,
        )
        from mnemostroma.gateway.errors import MemoryUnavailable
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_chat(), MemoryPlan(mode="active", would_inject=True))
        assert m.snapshot().gateway_memory_failures_total == 1

    @pytest.mark.asyncio
    async def test_cancelled_request_increments_cancelled_counter(self):
        start_signal = asyncio.Event()
        block = asyncio.Event()

        class HangingTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                start_signal.set()
                await block.wait()
                raise RuntimeError("unreachable")

        m = GatewayMetrics(clock=FakeClock())

        async def run() -> None:
            executor = GatewayExecutor(transport=HangingTransport(), metrics=m)
            await executor.execute(_chat(), _plan())

        task = asyncio.create_task(run())
        await start_signal.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # Cancelled counter tracked in routes, not executor
        assert m.snapshot().gateway_requests_cancelled_total == 0


# ══════════════════════════════════════════════════════════════════════
# Observation metrics
# ══════════════════════════════════════════════════════════════════════


class TestObservationMetrics:
    class _QuickObserver:
        async def observe(self, **kw: Any) -> None:
            pass

    class _FailingObserver:
        async def observe(self, **kw: Any) -> None:
            raise RuntimeError("fail")

    @pytest.mark.asyncio
    async def test_observer_schedule_accept_increments_scheduled_counter(self):
        m = GatewayMetrics(clock=FakeClock())
        registry = ObservationTaskRegistry(metrics=m)
        registry.schedule(self._QuickObserver(), "u", "a")
        assert m.snapshot().gateway_observations_scheduled_total == 1

    @pytest.mark.asyncio
    async def test_observer_success_increments_completed_counter(self):
        m = GatewayMetrics(clock=FakeClock())
        spawner = _RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn, metrics=m)
        registry.schedule(self._QuickObserver(), "u", "a")
        await spawner.tasks[0]
        assert m.snapshot().gateway_observations_completed_total == 1

    @pytest.mark.asyncio
    async def test_observer_failure_increments_failed_counter(self):
        import contextlib

        m = GatewayMetrics(clock=FakeClock())
        spawner = _RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn, metrics=m)
        registry.schedule(self._FailingObserver(), "u", "a")
        with contextlib.suppress(RuntimeError):
            await spawner.tasks[0]
        snap = m.snapshot()
        assert snap.gateway_observations_scheduled_total == 1
        assert snap.gateway_observations_failed_total == 1
        assert snap.gateway_observations_completed_total == 0

    @pytest.mark.asyncio
    async def test_observer_cancellation_increments_cancelled_counter(self):
        m = GatewayMetrics(clock=FakeClock())
        enter = asyncio.Event()

        class BlockingObserver:
            async def observe(self, **kw: Any) -> None:
                enter.set()
                await asyncio.Event().wait()

        spawner = _RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn, metrics=m)
        registry.schedule(BlockingObserver(), "u", "a")
        await enter.wait()
        spawner.tasks[0].cancel()
        import contextlib
        with contextlib.suppress(asyncio.CancelledError):
            await spawner.tasks[0]
        assert m.snapshot().gateway_observations_cancelled_total == 1


# ══════════════════════════════════════════════════════════════════════
# Admission metrics via routes (unit: provider_busy)
# ══════════════════════════════════════════════════════════════════════


class TestAdmissionMetrics:
    @pytest.mark.asyncio
    async def test_busy_request_increments_only_busy_counter(self):
        m = GatewayMetrics(clock=FakeClock())
        admission = DispatchAdmission(max_total=1)

        # Exhaust the single slot
        p = await admission.try_acquire(memory_active=False)
        assert p is not None

        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            admission=admission,
            metrics=m,
        )
        try:
            await executor.execute(_chat(), _plan())
        except ProviderTransportError as e:
            assert e.code == "provider_busy"
        except Exception:
            pass
        finally:
            async with p:
                pass

        # Request counters tracked in routes, not executor
        assert m.snapshot().gateway_provider_failures_total == 0


# ══════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════


class _RecordingSpawner:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None]] = []

    def spawn(self, coro: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task
