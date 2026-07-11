# SPDX-License-Identifier: FSL-1.1-MIT
"""Content-safe in-memory operational metrics.

No prompt text, completion content, memory XML, provider URL, token,
model name, request ID, or client IP is ever stored in metric names,
values, or labels.  Only stable category outcomes and numeric aggregates.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass(frozen=True)
class LatencyAggregate:
    count: int = 0
    sum_ms: float = 0.0
    min_ms: float = 0.0
    max_ms: float = 0.0


@dataclass(frozen=True)
class GatewayMetricsSnapshot:
    gateway_requests_total: int = 0
    gateway_requests_succeeded_total: int = 0
    gateway_requests_rejected_invalid_total: int = 0
    gateway_requests_rejected_busy_total: int = 0
    gateway_requests_cancelled_total: int = 0
    gateway_provider_failures_total: int = 0
    gateway_memory_failures_total: int = 0
    gateway_normalization_failures_total: int = 0
    gateway_observations_scheduled_total: int = 0
    gateway_observations_completed_total: int = 0
    gateway_observations_failed_total: int = 0
    gateway_observations_cancelled_total: int = 0
    gateway_validation_duration_ms: LatencyAggregate = field(
        default_factory=LatencyAggregate,
    )
    gateway_injection_duration_ms: LatencyAggregate = field(
        default_factory=LatencyAggregate,
    )
    gateway_dispatch_duration_ms: LatencyAggregate = field(
        default_factory=LatencyAggregate,
    )
    gateway_normalization_duration_ms: LatencyAggregate = field(
        default_factory=LatencyAggregate,
    )
    gateway_request_duration_ms: LatencyAggregate = field(
        default_factory=LatencyAggregate,
    )


class GatewayMetrics:
    """Thread-unsafe in-memory counters and latency aggregates.

    Designed for single-threaded asyncio event loop use.
    ``snapshot()`` returns an immutable ``GatewayMetricsSnapshot``.
    """

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock: Callable[[], float] = clock or time.perf_counter
        self._counters: dict[str, int] = {}
        self._latencies: dict[str, list[float]] = {}  # name → times in seconds

    # ── counter interface ────────────────────────────────────────────

    def increment(self, name: str) -> None:
        self._counters[name] = self._counters.get(name, 0) + 1

    # ── latency interface ────────────────────────────────────────────

    def record_start(self) -> float:
        return self._clock()

    def record_end(self, name: str, start_s: float) -> None:
        elapsed_s = self._clock() - start_s
        self._latencies.setdefault(name, []).append(elapsed_s)

    # ── snapshot ─────────────────────────────────────────────────────

    def snapshot(self) -> GatewayMetricsSnapshot:
        def _counter(key: str) -> int:
            return self._counters.get(key, 0)

        def _aggregate(key: str) -> LatencyAggregate:
            vals = self._latencies.get(key, [])
            if not vals:
                return LatencyAggregate()
            ms = [v * 1000.0 for v in vals]
            return LatencyAggregate(
                count=len(ms),
                sum_ms=sum(ms),
                min_ms=min(ms),
                max_ms=max(ms),
            )

        return GatewayMetricsSnapshot(
            gateway_requests_total=_counter("gateway_requests_total"),
            gateway_requests_succeeded_total=_counter("gateway_requests_succeeded_total"),
            gateway_requests_rejected_invalid_total=_counter("gateway_requests_rejected_invalid_total"),
            gateway_requests_rejected_busy_total=_counter("gateway_requests_rejected_busy_total"),
            gateway_requests_cancelled_total=_counter("gateway_requests_cancelled_total"),
            gateway_provider_failures_total=_counter("gateway_provider_failures_total"),
            gateway_memory_failures_total=_counter("gateway_memory_failures_total"),
            gateway_normalization_failures_total=_counter("gateway_normalization_failures_total"),
            gateway_observations_scheduled_total=_counter("gateway_observations_scheduled_total"),
            gateway_observations_completed_total=_counter("gateway_observations_completed_total"),
            gateway_observations_failed_total=_counter("gateway_observations_failed_total"),
            gateway_observations_cancelled_total=_counter("gateway_observations_cancelled_total"),
            gateway_validation_duration_ms=_aggregate("gateway_validation_duration_ms"),
            gateway_injection_duration_ms=_aggregate("gateway_injection_duration_ms"),
            gateway_dispatch_duration_ms=_aggregate("gateway_dispatch_duration_ms"),
            gateway_normalization_duration_ms=_aggregate("gateway_normalization_duration_ms"),
            gateway_request_duration_ms=_aggregate("gateway_request_duration_ms"),
        )
