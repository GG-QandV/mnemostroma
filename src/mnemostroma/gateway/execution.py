# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import asyncio
import json
from typing import Any

from mnemostroma.gateway.admission import DispatchAdmission
from mnemostroma.gateway.contracts import ChatRequest, MemoryPlan
from mnemostroma.gateway.errors import GatewayExecutionError, MemoryUnavailable
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.materialize import materialize_provider_request
from mnemostroma.gateway.memory_injector import MemoryInjector
from mnemostroma.gateway.metrics import GatewayMetrics
from mnemostroma.gateway.normalize import normalize_completion
from mnemostroma.gateway.observer import (
    ObservationTaskRegistry,
    assistant_content,
    last_user_content,
)
from mnemostroma.gateway.provider import ProviderTransport
from mnemostroma.gateway.provider_errors import ProviderTransportError

_MEMORY_CAP = 24_000


class GatewayExecutor:
    def __init__(
        self,
        transport: ProviderTransport | None = None,
        memory_injector: MemoryInjector | None = None,
        completion_observer: Any = None,
        observation_registry: ObservationTaskRegistry | None = None,
        admission: DispatchAdmission | None = None,
        metrics: GatewayMetrics | None = None,
    ) -> None:
        self._transport = transport or FakeProviderTransport()
        self._memory_injector = memory_injector
        self._observer = completion_observer
        self._observation_registry = observation_registry or ObservationTaskRegistry()
        self._admission = admission
        self._metrics = metrics

    async def execute(
        self,
        chat_request: ChatRequest,
        memory: MemoryPlan,
    ) -> dict[str, Any]:
        if chat_request.stream:
            raise GatewayExecutionError(
                "stream=true is not supported in current dispatch mode"
            )

        if self._admission is not None:
            permit = await self._admission.try_acquire(
                memory_active=memory.mode == "active",
            )
            if permit is None:
                raise ProviderTransportError(
                    503, "provider_busy",
                    "dispatch limit exhausted",
                )
        else:
            permit = None

        async with permit or _NullPermit():
            injected_context: str | None = None

            if memory.mode == "active":
                injected_context = await self._inject_memory(chat_request)

            provider_req = materialize_provider_request(
                chat_request, memory, injected_context
            )

            dispatch_start = _record_start(self._metrics)
            try:
                provider_resp = await self._transport.send(provider_req)
            except asyncio.CancelledError:
                raise
            except ProviderTransportError:
                _record_end(self._metrics, "gateway_dispatch_duration_ms", dispatch_start)
                self._incr("gateway_provider_failures_total")
                raise
            except Exception:
                _record_end(self._metrics, "gateway_dispatch_duration_ms", dispatch_start)
                self._incr("gateway_provider_failures_total")
                raise
            _record_end(self._metrics, "gateway_dispatch_duration_ms", dispatch_start)

            raw = json.loads(provider_resp.body)

            norm_start = _record_start(self._metrics)
            try:
                completion = normalize_completion(raw, chat_request.model)
            except asyncio.CancelledError:
                raise
            except ProviderTransportError:
                _record_end(self._metrics, "gateway_normalization_duration_ms", norm_start)
                self._incr("gateway_normalization_failures_total")
                raise
            except Exception:
                _record_end(self._metrics, "gateway_normalization_duration_ms", norm_start)
                self._incr("gateway_normalization_failures_total")
                raise
            _record_end(self._metrics, "gateway_normalization_duration_ms", norm_start)

            if self._observer is not None:
                self._schedule_observe(chat_request, completion)

            return completion

    def _incr(self, name: str) -> None:
        if self._metrics is not None:
            self._metrics.increment(name)

    def _schedule_observe(
        self,
        chat_request: ChatRequest,
        completion: dict[str, Any],
    ) -> None:
        user_msg = last_user_content(chat_request)
        assistant_msg = assistant_content(completion)
        if user_msg is None or assistant_msg is None:
            return

        self._observation_registry.schedule(
            self._observer,
            user_msg,
            assistant_msg,
        )

    async def _inject_memory(self, chat_request: ChatRequest) -> str:
        if self._memory_injector is None:
            _record_end(self._metrics, "gateway_injection_duration_ms",
                        _record_start(self._metrics))
            self._incr("gateway_memory_failures_total")
            raise MemoryUnavailable(
                "memory_mode=active requires a wired memory injector"
            )

        user_content: str | None = None
        for msg in reversed(chat_request.messages):
            if msg.role == "user":
                user_content = msg.content
                break

        if user_content is None:
            _record_end(self._metrics, "gateway_injection_duration_ms",
                        _record_start(self._metrics))
            self._incr("gateway_memory_failures_total")
            raise GatewayExecutionError(
                "memory_mode=active requires at least one user message"
            )

        inj_start = _record_start(self._metrics)
        try:
            result = await self._memory_injector.inject(user_content)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _record_end(self._metrics, "gateway_injection_duration_ms", inj_start)
            self._incr("gateway_memory_failures_total")
            raise MemoryUnavailable(
                f"memory injector failed: {exc}"
            ) from exc

        _record_end(self._metrics, "gateway_injection_duration_ms", inj_start)

        self._validate_injection(result)
        return result

    @staticmethod
    def _validate_injection(result: Any) -> None:
        if not isinstance(result, str):
            raise MemoryUnavailable(
                "memory injector returned non-string result"
            )
        if not result or not result.strip():
            raise MemoryUnavailable(
                "memory injector returned blank result"
            )
        if "\x00" in result:
            raise MemoryUnavailable(
                "memory injector returned result containing NUL"
            )
        if len(result) > _MEMORY_CAP:
            raise MemoryUnavailable(
                f"memory injection exceeds {_MEMORY_CAP} character cap"
            )


class _NullPermit:
    """No-op async context manager when admission is not configured."""

    async def __aenter__(self) -> _NullPermit:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass


def _record_start(metrics: GatewayMetrics | None) -> float:
    if metrics is None:
        return 0.0
    return metrics.record_start()


def _record_end(
    metrics: GatewayMetrics | None,
    name: str,
    start_s: float,
) -> None:
    if metrics is None:
        return
    metrics.record_end(name, start_s)
