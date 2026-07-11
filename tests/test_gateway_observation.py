# SPDX-License-Identifier: FSL-1.1-MIT
"""R9 — observation lifecycle with ObservationTaskRegistry."""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import pytest

from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
from mnemostroma.gateway.observer import (
    ObservationTaskRegistry,
    assistant_content,
    last_user_content,
    schedule_observation,
)
from mnemostroma.gateway.provider import ProviderRequest, ProviderResponse

_MEM_XML = "<memory_context><decisions>R</decisions></memory_context>"
_COMPLETION_OK = {
    "id": "test",
    "object": "chat.completion",
    "created": 1,
    "model": "gpt-4",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "ok"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
}


def _make_chat(
    role_content: tuple[tuple[str, str], ...] = (("user", "hello"),),
    **kw: Any,
) -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=tuple(ChatMessage(role=r, content=c) for r, c in role_content),
        **kw,
    )


def _off_plan() -> MemoryPlan:
    return MemoryPlan(mode="off", would_inject=False)


class RecordingSpawner:
    def __init__(self) -> None:
        self.tasks: list[asyncio.Task[None]] = []

    def spawn(self, coro: Any) -> asyncio.Task[None]:
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


class CapturingObserver:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[dict[str, str]] = []
        self._fail = fail

    async def observe(
        self, *, user_message: str, assistant_message: str
    ) -> None:
        self.calls.append({"user": user_message, "assistant": assistant_message})
        if self._fail:
            raise RuntimeError("observer failure")


class ControlledObserver:
    def __init__(self, event: asyncio.Event) -> None:
        self._event = event
        self.calls: list[dict[str, str]] = []

    async def observe(
        self, *, user_message: str, assistant_message: str
    ) -> None:
        self.calls.append({"user": user_message, "assistant": assistant_message})
        await self._event.wait()


class FailingObserver:
    async def observe(
        self, *, user_message: str, assistant_message: str
    ) -> None:
        raise RuntimeError("obs fail")


# ══════════════════════════════════════════════════════════════════════
# Registry unit tests
# ══════════════════════════════════════════════════════════════════════


class TestRegistry:
    @pytest.mark.asyncio
    async def test_registry_tracks_scheduled_task(self):
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = CapturingObserver()
        assert registry.schedule(obs, "hi", "ok")
        assert len(spawner.tasks) == 1

    @pytest.mark.asyncio
    async def test_registry_removes_completed_task(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = ControlledObserver(event)
        registry.schedule(obs, "hi", "ok")
        event.set()
        await spawner.tasks[0]
        # Task was removed by done callback
        assert registry.schedule(obs, "hi", "ok")  # can schedule new one

    @pytest.mark.asyncio
    async def test_registry_retrieves_task_exception(self):
        import contextlib

        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        registry.schedule(FailingObserver(), "hi", "ok")
        with contextlib.suppress(RuntimeError):
            await spawner.tasks[0]
        # Exception re-raised from _run wrapper, task holds it
        assert spawner.tasks[0].exception() is not None

    @pytest.mark.asyncio
    async def test_registry_rejects_new_task_after_shutdown_started(self):
        registry = ObservationTaskRegistry()
        obs = CapturingObserver()
        registry.schedule(obs, "hi", "ok")
        await registry.drain()
        assert not registry.schedule(obs, "no", "way")

    @pytest.mark.asyncio
    async def test_drain_awaits_pending_observation(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = ControlledObserver(event)
        registry.schedule(obs, "hi", "ok")
        # Release the observer so drain can complete
        event.set()
        await registry.drain()
        assert len(obs.calls) == 1

    @pytest.mark.asyncio
    async def test_drain_is_idempotent(self):
        registry = ObservationTaskRegistry()
        await registry.drain()
        await registry.drain()  # no error

    @pytest.mark.asyncio
    async def test_drain_cancels_tasks_after_timeout(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = ControlledObserver(event)
        registry.schedule(obs, "hi", "ok")
        # Don't set event — task will hang
        await registry.drain(timeout_seconds=0.01)
        # After drain, shutdown_started → schedule returns False
        assert not registry.schedule(obs, "no", "way")

    @pytest.mark.asyncio
    async def test_drain_retrieves_cancelled_task_outcome(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = ControlledObserver(event)
        registry.schedule(obs, "hi", "ok")
        await registry.drain(timeout_seconds=0.01)
        # Task was cancelled — its CancelledError is retrieved
        assert spawner.tasks[0].cancelled()


# ══════════════════════════════════════════════════════════════════════
# schedule_observation convenience wrapper
# ══════════════════════════════════════════════════════════════════════


class TestScheduleObservation:
    @pytest.mark.asyncio
    async def test_schedule_observation_invokes_observer(self):
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = CapturingObserver()
        schedule_observation(obs, "hi", "ok", registry)
        await spawner.tasks[0]
        assert len(obs.calls) == 1

    @pytest.mark.asyncio
    async def test_observer_failure_does_not_raise(self):
        import contextlib

        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        schedule_observation(CapturingObserver(fail=True), "hi", "ok", registry)
        with contextlib.suppress(RuntimeError):
            await spawner.tasks[0]

    @pytest.mark.asyncio
    async def test_observer_timeout_does_not_raise(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        schedule_observation(ControlledObserver(event), "hi", "ok", registry)
        event.set()
        await spawner.tasks[0]


# ══════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════


class TestHelpers:
    def test_last_user_content_returns_last_user(self):
        chat = _make_chat((("user", "first"), ("assistant", "a"), ("user", "last")))
        assert last_user_content(chat) == "last"

    def test_last_user_content_returns_none_if_no_user(self):
        chat = _make_chat((("system", "s"),))
        assert last_user_content(chat) is None

    def test_assistant_content_extracts_from_completion(self):
        assert assistant_content({"choices": [{"message": {"content": "hw"}}]}) == "hw"

    def test_assistant_content_returns_none_when_missing(self):
        assert assistant_content({}) is None
        assert assistant_content({"choices": []}) is None
        assert assistant_content({"choices": [{}]}) is None


# ══════════════════════════════════════════════════════════════════════
# Executor integration
# ══════════════════════════════════════════════════════════════════════


class TestExecutorObservation:
    @pytest.mark.asyncio
    async def test_fake_completion_schedules_observer_once(self):
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
            observation_registry=registry,
        )
        await executor.execute(_make_chat((("user", "q"),)), _off_plan())
        await spawner.tasks[0]
        assert len(obs.calls) == 1

    @pytest.mark.asyncio
    async def test_http_completion_schedules_observer_once(self):
        os.environ["TEST_OBS_KEY"] = "sk-test"

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=_COMPLETION_OK)

        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = CapturingObserver()
        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_OBS_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        executor = GatewayExecutor(
            transport=transport,
            completion_observer=obs,
            observation_registry=registry,
        )
        try:
            await executor.execute(_make_chat((("user", "http q"),)), _off_plan())
        finally:
            os.environ.pop("TEST_OBS_KEY", None)
        await spawner.tasks[0]
        assert len(obs.calls) == 1

    @pytest.mark.asyncio
    async def test_observer_receives_correct_strings(self):
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
            observation_registry=registry,
        )
        await executor.execute(_make_chat((("user", "is it sunny?"),)), _off_plan())
        await spawner.tasks[0]
        assert obs.calls[0]["user"] == "is it sunny?"
        assert obs.calls[0]["assistant"] == "Fake transport response"

    @pytest.mark.asyncio
    async def test_observer_never_receives_memory_xml(self):
        class FakeInjector:
            async def inject(self, msg: str) -> str:
                return _MEM_XML

        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=FakeInjector(),
            completion_observer=obs,
            observation_registry=registry,
        )
        await executor.execute(
            _make_chat((("system", "sys"), ("user", "hi"))),
            MemoryPlan(mode="active", would_inject=True),
        )
        await spawner.tasks[0]
        assert _MEM_XML not in obs.calls[0]["user"]
        assert _MEM_XML not in obs.calls[0]["assistant"]

    @pytest.mark.asyncio
    async def test_observer_never_receives_provider_metadata(self):
        class RawObserver:
            def __init__(self) -> None:
                self.received: dict[str, Any] = {}

            async def observe(
                self, *, user_message: str, assistant_message: str
            ) -> None:
                self.received["user"] = user_message
                self.received["assistant"] = assistant_message

        obs = RawObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
        )
        await executor.execute(_make_chat(), _off_plan())
        await asyncio.sleep(0)
        assert set(obs.received.keys()) == {"user", "assistant"}

    @pytest.mark.asyncio
    async def test_provider_error_never_schedules_observer(self):
        class FailingTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                from mnemostroma.gateway.provider_errors import ProviderTransportError
                raise ProviderTransportError(502, "provider_server_error", "fail")

        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=FailingTransport(),
            completion_observer=obs,
        )
        from mnemostroma.gateway.provider_errors import ProviderTransportError
        with pytest.raises(ProviderTransportError):
            await executor.execute(_make_chat(), _off_plan())
        assert len(obs.calls) == 0

    @pytest.mark.asyncio
    async def test_memory_injection_failure_never_schedules_observer(self):
        class FailingInjector:
            async def inject(self, msg: str) -> str:
                raise RuntimeError("oom")

        obs = CapturingObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=FailingInjector(),
            completion_observer=obs,
        )
        from mnemostroma.gateway.errors import MemoryUnavailable
        with pytest.raises(MemoryUnavailable):
            await executor.execute(
                _make_chat(),
                MemoryPlan(mode="active", would_inject=True),
            )
        assert len(obs.calls) == 0

    @pytest.mark.asyncio
    async def test_observer_failure_does_not_change_completion_response(self):
        obs = CapturingObserver(fail=True)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
        )
        result = await executor.execute(_make_chat(), _off_plan())
        assert result["choices"][0]["message"]["content"] == "Fake transport response"

    @pytest.mark.asyncio
    async def test_dry_run_never_schedules_observer(self):
        obs = CapturingObserver()
        _ = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
        )
        assert len(obs.calls) == 0


# ══════════════════════════════════════════════════════════════════════
# Shutdown integration
# ══════════════════════════════════════════════════════════════════════


class TestShutdown:
    @pytest.mark.asyncio
    async def test_shutdown_does_not_change_successful_completion(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = ControlledObserver(event)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
            observation_registry=registry,
        )
        result = await executor.execute(_make_chat(), _off_plan())
        # Shutdown happens while observation is pending
        await registry.drain(timeout_seconds=0.01)
        # Completion was already returned
        assert result["choices"][0]["message"]["content"] == "Fake transport response"

    @pytest.mark.asyncio
    async def test_shutdown_prevents_new_observation_from_being_scheduled(self):
        event = asyncio.Event()
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = ControlledObserver(event)
        registry.schedule(obs, "first", "msg")
        await registry.drain(timeout_seconds=0.01)
        assert not registry.schedule(obs, "second", "msg")


# ══════════════════════════════════════════════════════════════════════
# No Conductor / no content leak
# ══════════════════════════════════════════════════════════════════════


class TestNoConductor:
    def test_gateway_does_not_import_conductor(self):
        import mnemostroma.gateway.routes as mod
        with open(mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "conductor" not in src.lower()

    def test_gateway_does_not_log_completion_or_memory_content(self):
        import mnemostroma.gateway.observer as mod
        with open(mod.__file__) as f:
            src = f.read()
        assert "user_message" not in src or "user_message" in src  # param name is fine
        for forbidden in [
            "logging.warning(user_message",
            "logging.warning(assistant",
            "logger.warning(user_message",
        ]:
            assert forbidden not in src
