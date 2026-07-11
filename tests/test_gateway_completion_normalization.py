# SPDX-License-Identifier: FSL-1.1-MIT
"""R10 — provider completion normalization."""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
from mnemostroma.gateway.normalize import normalize_completion
from mnemostroma.gateway.observer import ObservationTaskRegistry
from mnemostroma.gateway.provider_errors import ProviderTransportError

_TEST_MODEL = "gpt-4"
_CALLBACK_COUNT = iter(range(10_000))


def _clock() -> float:
    return 1_700_000_000.0


def _id_factory() -> str:
    return f"chatcmpl_mnemo_test_{next(_CALLBACK_COUNT)}"


_COMPLETION_OK = {
    "choices": [
        {
            "message": {"content": "hello world"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5},
}


def _make_chat(
    role_content: tuple[tuple[str, str], ...] = (("user", "hello"),),
) -> ChatRequest:
    return ChatRequest(
        model=_TEST_MODEL,
        messages=tuple(ChatMessage(role=r, content=c) for r, c in role_content),
    )


def _off_plan() -> MemoryPlan:
    return MemoryPlan(mode="off", would_inject=False)


class RecordingSpawner:
    def __init__(self) -> None:
        self.tasks: list[Any] = []

    def spawn(self, coro: Any) -> Any:
        import asyncio
        task = asyncio.create_task(coro)
        self.tasks.append(task)
        return task


class RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def observe(
        self, *, user_message: str, assistant_message: str
    ) -> None:
        self.calls.append({"u": user_message, "a": assistant_message})


# ══════════════════════════════════════════════════════════════════════
# Core normalizer behaviour
# ══════════════════════════════════════════════════════════════════════


class TestNormalizerOutput:
    def test_normalizer_generates_gateway_owned_id(self):
        result = normalize_completion(_COMPLETION_OK, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["id"].startswith("chatcmpl_mnemo_")

    def test_normalizer_uses_current_epoch_timestamp(self):
        result = normalize_completion(_COMPLETION_OK, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["created"] == 1_700_000_000

    def test_normalizer_uses_requested_model_not_upstream_model(self):
        body = {**_COMPLETION_OK, "model": "upstream-model"}
        result = normalize_completion(body, "my-model", clock=_clock, id_factory=_id_factory)
        assert result["model"] == "my-model"

    def test_normalizer_always_emits_chat_completion_object(self):
        result = normalize_completion(_COMPLETION_OK, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["object"] == "chat.completion"

    def test_normalizer_emits_exactly_one_assistant_choice(self):
        result = normalize_completion(_COMPLETION_OK, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert len(result["choices"]) == 1
        assert result["choices"][0]["index"] == 0
        assert result["choices"][0]["message"]["role"] == "assistant"

    def test_normalizer_preserves_valid_content_exactly(self):
        result = normalize_completion(_COMPLETION_OK, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["choices"][0]["message"]["content"] == "hello world"

    def test_normalizer_normalizes_unknown_finish_reason_to_stop(self):
        body = dict(_COMPLETION_OK)
        body["choices"] = [dict(body["choices"][0], finish_reason="tool_call")]
        result = normalize_completion(body, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["choices"][0]["finish_reason"] == "stop"

    def test_normalizer_preserves_allowed_finish_reasons(self):
        for fr in ("stop", "length", "content_filter"):
            body = dict(_COMPLETION_OK)
            body["choices"] = [dict(body["choices"][0], finish_reason=fr)]
            result = normalize_completion(body, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
            assert result["choices"][0]["finish_reason"] == fr

    def test_normalizer_defaults_missing_usage_to_zero(self):
        body = dict(_COMPLETION_OK)
        del body["usage"]
        result = normalize_completion(body, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["usage"] == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def test_normalizer_recomputes_usage_total(self):
        result = normalize_completion(_COMPLETION_OK, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["usage"]["total_tokens"] == 15

    def test_normalizer_normalizes_each_invalid_usage_field_to_zero(self):
        body = dict(_COMPLETION_OK)
        body["usage"] = {"prompt_tokens": -1, "completion_tokens": "abc"}
        result = normalize_completion(body, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["usage"]["prompt_tokens"] == 0
        assert result["usage"]["completion_tokens"] == 0
        assert result["usage"]["total_tokens"] == 0

    def test_normalizer_ignores_upstream_id_model_and_extra_fields(self):
        body = {
            **_COMPLETION_OK,
            "id": "upstream-id-xyz",
            "model": "upstream-gpt-5",
            "system_fingerprint": "fp_abc",
            "extra_metadata": {"foo": "bar"},
        }
        result = normalize_completion(body, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert result["id"].startswith("chatcmpl_mnemo_")
        assert result["model"] == _TEST_MODEL
        assert "system_fingerprint" not in result
        assert "extra_metadata" not in result


# ══════════════════════════════════════════════════════════════════════
# Error mapping
# ══════════════════════════════════════════════════════════════════════


class TestNormalizerErrors:
    def _assert_invalid(self, body: dict[str, Any]) -> None:
        with pytest.raises(ProviderTransportError) as exc:
            normalize_completion(body, _TEST_MODEL, clock=_clock, id_factory=_id_factory)
        assert exc.value.code == "provider_invalid_response"
        assert exc.value.status == 502

    def test_missing_choices_maps_to_provider_invalid_response(self):
        self._assert_invalid({})

    def test_empty_choices_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": []})

    def test_non_list_choices_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": "notlist"})

    def test_missing_message_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{}]})

    def test_missing_content_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{"message": {}}]})

    def test_null_content_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{"message": {"content": None}}]})

    def test_nonstring_content_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{"message": {"content": ["x"]}}]})

    def test_blank_content_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{"message": {"content": "   "}}]})

    def test_nul_content_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{"message": {"content": "ok\x00bad"}}]})

    def test_oversize_content_maps_to_provider_invalid_response(self):
        self._assert_invalid({"choices": [{"message": {"content": "x" * 100_001}}]})


# ══════════════════════════════════════════════════════════════════════
# Integration through executor
# ══════════════════════════════════════════════════════════════════════


class TestExecutorIntegration:
    @pytest.mark.asyncio
    async def test_fake_dispatch_returns_gateway_normalized_completion(self):
        executor = GatewayExecutor(transport=FakeProviderTransport())
        result = await executor.execute(_make_chat(), _off_plan())
        assert result["id"].startswith("chatcmpl_mnemo_")
        assert result["object"] == "chat.completion"
        assert result["model"] == _TEST_MODEL

    @pytest.mark.asyncio
    async def test_http_dispatch_returns_gateway_normalized_completion(self):
        os.environ["TEST_NORM_KEY"] = "sk-test"

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            return httpx.Response(200, json={
                "choices": [
                    {
                        "message": {"content": body.get("model", "ok")},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 2},
            })

        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_NORM_KEY",
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
        executor = GatewayExecutor(transport=transport)
        try:
            result = await executor.execute(_make_chat(), _off_plan())
        finally:
            os.environ.pop("TEST_NORM_KEY", None)
        assert result["id"].startswith("chatcmpl_mnemo_")
        assert result["object"] == "chat.completion"
        assert result["model"] == _TEST_MODEL
        assert result["choices"][0]["message"]["content"] == _TEST_MODEL

    @pytest.mark.asyncio
    async def test_observer_receives_normalized_content_only(self):
        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = RecordingObserver()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            completion_observer=obs,
            observation_registry=registry,
        )
        await executor.execute(_make_chat((("user", "my q"),)), _off_plan())
        await spawner.tasks[0]
        assert obs.calls[0]["a"] == "Fake transport response"

    @pytest.mark.asyncio
    async def test_normalization_failure_never_schedules_observation(self):
        class BadTransport:
            async def send(self, request: Any) -> Any:
                from mnemostroma.gateway.provider import ProviderResponse
                return ProviderResponse(status=200, body=json.dumps({"choices": []}))

        spawner = RecordingSpawner()
        registry = ObservationTaskRegistry(spawner=spawner.spawn)
        obs = RecordingObserver()
        executor = GatewayExecutor(
            transport=BadTransport(),
            completion_observer=obs,
            observation_registry=registry,
        )
        with pytest.raises(ProviderTransportError):
            await executor.execute(_make_chat(), _off_plan())
        assert len(obs.calls) == 0
