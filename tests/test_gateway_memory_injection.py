# SPDX-License-Identifier: FSL-1.1-MIT
"""R7 — Memory injection into provider dispatch.

Tests verify that:
- Memory retrieval only runs when memory_mode="active"
- Result is inserted as a separate system message after existing system messages
- Original ChatRequest is never mutated
- All transport layers (fake, http) receive the injected context
- Failure policies produce 503 without transport dispatch
- Gateway never imports Conductor or calls observe
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx
import pytest

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest, MemoryPlan
from mnemostroma.gateway.errors import GatewayExecutionError
from mnemostroma.gateway.execution import GatewayExecutor
from mnemostroma.gateway.fake_transport import FakeProviderTransport
from mnemostroma.gateway.httpx_transport import HttpxProviderTransport
from mnemostroma.gateway.memory_injector import ConductorMemoryInjector
from mnemostroma.gateway.provider import ProviderRequest, ProviderResponse

_MEM_XML = "<memory_context><decisions>R</decisions></memory_context>"
_MEM_CAP = 24_000
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


class FakeMemoryInjector:
    def __init__(self, result: str = _MEM_XML) -> None:
        self._result = result
        self.call_args: list[str] = []
        self.call_count: int = 0

    async def inject(self, user_message: str) -> str:
        self.call_count += 1
        self.call_args.append(user_message)
        return self._result


class FailingMemoryInjector:
    async def inject(self, user_message: str) -> str:
        raise RuntimeError("injection failed")


class NonStringMemoryInjector:
    async def inject(self, user_message: str) -> str:
        return {"not": "a string"}  # type: ignore[return-value]


class BlankMemoryInjector:
    def __init__(self, result: str = "   ") -> None:
        self._result = result

    async def inject(self, user_message: str) -> str:
        return self._result


def _make_chat(
    role_content: tuple[tuple[str, str], ...] = (("user", "hello"),),
    **kw: Any,
) -> ChatRequest:
    return ChatRequest(
        model="gpt-4",
        messages=tuple(ChatMessage(role=r, content=c) for r, c in role_content),
        **kw,
    )


def _active_plan() -> MemoryPlan:
    return MemoryPlan(mode="active", would_inject=True)


# ══════════════════════════════════════════════════════════════════════
# Config-level tests
# ══════════════════════════════════════════════════════════════════════


class TestMemoryModeConfig:
    def test_memory_mode_defaults_to_off(self):
        cfg = GatewayConfig()
        assert cfg.memory_mode == "off"

    def test_memory_mode_rejects_unknown_value(self):
        from mnemostroma.gateway.errors import GatewayConfigError
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(memory_mode="invalid")  # type: ignore[arg-type]
        with pytest.raises(GatewayConfigError, match="memory_mode"):
            validate_gateway_config(cfg)

    def test_memory_mode_accepts_active(self):
        from mnemostroma.gateway.policy import validate_gateway_config
        cfg = GatewayConfig(memory_mode="active")
        validate_gateway_config(cfg)


# ══════════════════════════════════════════════════════════════════════
# Injector not invoked in non-active modes
# ══════════════════════════════════════════════════════════════════════


class TestInjectorNotInvoked:
    @pytest.mark.asyncio
    async def test_dry_run_never_invokes_memory_injector(self):
        injector = FakeMemoryInjector()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )
        await executor.execute(
            _make_chat(),
            MemoryPlan(mode="off", would_inject=False),
        )
        assert injector.call_count == 0

    @pytest.mark.asyncio
    async def test_planned_mode_never_invokes_memory_injector(self):
        injector = FakeMemoryInjector()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )
        await executor.execute(
            _make_chat(),
            MemoryPlan(mode="planned", would_inject=True),
        )
        assert injector.call_count == 0


# ══════════════════════════════════════════════════════════════════════
# Active mode behaviour
# ══════════════════════════════════════════════════════════════════════


class TestActiveModeInjection:
    @pytest.mark.asyncio
    async def test_active_mode_requires_wired_injector(self):
        from mnemostroma.gateway.errors import MemoryUnavailable
        executor = GatewayExecutor(transport=FakeProviderTransport())
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_make_chat(), _active_plan())

    @pytest.mark.asyncio
    async def test_active_mode_injects_for_last_user_message_once(self):
        injector = FakeMemoryInjector(_MEM_XML)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("user", "hello"),
            ("assistant", "hi"),
            ("user", "what about retries?"),
        ))
        await executor.execute(chat, _active_plan())
        assert injector.call_count == 1
        assert injector.call_args[0] == "what about retries?"

    @pytest.mark.asyncio
    async def test_active_mode_preserves_original_message_order(self):
        injector = FakeMemoryInjector(_MEM_XML)
        # Capture provider request
        captured: list[ProviderRequest] = []

        class CapturingTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                captured.append(req)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=CapturingTransport(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "be concise"),
            ("user", "q1"),
            ("assistant", "a1"),
            ("user", "q2"),
        ))
        await executor.execute(chat, _active_plan())
        roles = [m["role"] for m in captured[0].messages]
        contents = [m["content"] for m in captured[0].messages]
        assert roles == ["system", "system", "user", "assistant", "user"]
        assert contents[0] == "be concise"
        assert contents[2] == "q1"
        assert contents[3] == "a1"
        assert contents[4] == "q2"

    @pytest.mark.asyncio
    async def test_active_mode_inserts_memory_after_existing_system_messages(self):
        injector = FakeMemoryInjector(_MEM_XML)
        captured: list[ProviderRequest] = []

        class CapturingTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                captured.append(req)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=CapturingTransport(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "sys1"),
            ("system", "sys2"),
            ("user", "test"),
        ))
        await executor.execute(chat, _active_plan())
        messages = captured[0].messages
        assert messages[0]["content"] == "sys1"
        assert messages[1]["content"] == "sys2"
        assert messages[2]["content"] == _MEM_XML
        assert messages[2]["role"] == "system"
        assert messages[3]["content"] == "test"

    @pytest.mark.asyncio
    async def test_active_mode_inserts_memory_before_first_non_system(self):
        injector = FakeMemoryInjector(_MEM_XML)
        captured: list[ProviderRequest] = []

        class CapturingTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                captured.append(req)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=CapturingTransport(),
            memory_injector=injector,
        )
        # No system messages in the original
        chat = _make_chat((
            ("user", "test"),
        ))
        await executor.execute(chat, _active_plan())
        messages = captured[0].messages
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == _MEM_XML
        assert messages[1]["content"] == "test"

    @pytest.mark.asyncio
    async def test_active_mode_does_not_replace_system_prompt(self):
        injector = FakeMemoryInjector(_MEM_XML)
        captured: list[ProviderRequest] = []

        class CapturingTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                captured.append(req)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=CapturingTransport(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "You are a coder"),
            ("user", "write a function"),
        ))
        await executor.execute(chat, _active_plan())
        messages = captured[0].messages
        assert messages[0]["content"] == "You are a coder"
        assert messages[1]["content"] == _MEM_XML
        assert messages[2]["content"] == "write a function"

    @pytest.mark.asyncio
    async def test_active_mode_does_not_mutate_original_chat_request(self):
        injector = FakeMemoryInjector(_MEM_XML)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "be concise"),
            ("user", "hello"),
        ))
        original = chat.messages
        await executor.execute(chat, _active_plan())
        assert chat.messages is original
        assert len(chat.messages) == 2
        assert chat.messages[0].content == "be concise"
        assert chat.messages[1].content == "hello"

    @pytest.mark.asyncio
    async def test_active_mode_fake_transport_receives_memory_system_message(
        self, monkeypatch
    ):
        injector = FakeMemoryInjector(_MEM_XML)
        captured: list[ProviderRequest] = []

        class CapturingFake:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                captured.append(req)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=CapturingFake(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "sys"),
            ("user", "q"),
        ))
        await executor.execute(chat, _active_plan())
        msgs = captured[0].messages
        assert _MEM_XML in [m["content"] for m in msgs]
        assert msgs[1]["role"] == "system"

    @pytest.mark.asyncio
    async def test_active_mode_http_transport_receives_memory_system_message(self):
        os.environ["TEST_MEM_KEY"] = "sk-test"
        captured: dict[str, Any] = {}

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            captured["messages"] = body["messages"]
            return httpx.Response(200, json=_COMPLETION_OK)

        injector = FakeMemoryInjector(_MEM_XML)
        transport = HttpxProviderTransport(
            base_url="https://api.openai.com/v1",
            token_env="TEST_MEM_KEY",
            http_client=httpx.AsyncClient(
                transport=httpx.MockTransport(handler),
            ),
        )
        executor = GatewayExecutor(
            transport=transport,
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "sys"),
            ("user", "q"),
        ))
        try:
            await executor.execute(chat, _active_plan())
        finally:
            os.environ.pop("TEST_MEM_KEY", None)

        msgs = captured["messages"]
        contents = [m["content"] for m in msgs]
        assert _MEM_XML in contents
        assert msgs[1]["role"] == "system"

    @pytest.mark.asyncio
    async def test_active_memory_never_appears_in_completion_response(self):
        injector = FakeMemoryInjector(_MEM_XML)
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )
        result = await executor.execute(
            _make_chat((("user", "hello"),)),
            _active_plan(),
        )
        result_text = json.dumps(result)
        assert _MEM_XML not in result_text
        assert "memory_context" not in result_text


# ══════════════════════════════════════════════════════════════════════
# Failure policy
# ══════════════════════════════════════════════════════════════════════


class TestFailurePolicy:
    @pytest.mark.asyncio
    async def test_memory_injector_failure_returns_503_without_transport_call(
        self,
    ):
        from mnemostroma.gateway.errors import MemoryUnavailable

        transport_called: list[int] = []

        class NoCallTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                transport_called.append(1)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=NoCallTransport(),
            memory_injector=FailingMemoryInjector(),
        )
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_make_chat(), _active_plan())
        assert len(transport_called) == 0

    @pytest.mark.asyncio
    async def test_non_string_memory_returns_503_without_transport_call(self):
        from mnemostroma.gateway.errors import MemoryUnavailable

        transport_called: list[int] = []

        class NoCallTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                transport_called.append(1)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=NoCallTransport(),
            memory_injector=NonStringMemoryInjector(),
        )
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_make_chat(), _active_plan())
        assert len(transport_called) == 0

    @pytest.mark.asyncio
    async def test_blank_memory_returns_503_without_transport_call(self):
        from mnemostroma.gateway.errors import MemoryUnavailable

        transport_called: list[int] = []

        class NoCallTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                transport_called.append(1)
                return await FakeProviderTransport().send(req)

        executor = GatewayExecutor(
            transport=NoCallTransport(),
            memory_injector=BlankMemoryInjector(),
        )
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_make_chat(), _active_plan())
        assert len(transport_called) == 0

    @pytest.mark.asyncio
    async def test_oversize_memory_returns_503_without_transport_call(self):
        from mnemostroma.gateway.errors import MemoryUnavailable

        transport_called: list[int] = []

        class NoCallTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                transport_called.append(1)
                return await FakeProviderTransport().send(req)

        big = "x" * (_MEM_CAP + 1)
        injector = FakeMemoryInjector(big)
        executor = GatewayExecutor(
            transport=NoCallTransport(),
            memory_injector=injector,
        )
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_make_chat(), _active_plan())
        assert len(transport_called) == 0

    @pytest.mark.asyncio
    async def test_nul_memory_returns_503_without_transport_call(self):
        from mnemostroma.gateway.errors import MemoryUnavailable

        transport_called: list[int] = []

        class NoCallTransport:
            async def send(self, req: ProviderRequest) -> ProviderResponse:
                transport_called.append(1)
                return await FakeProviderTransport().send(req)

        injector = FakeMemoryInjector("ok\x00bad")
        executor = GatewayExecutor(
            transport=NoCallTransport(),
            memory_injector=injector,
        )
        with pytest.raises(MemoryUnavailable):
            await executor.execute(_make_chat(), _active_plan())
        assert len(transport_called) == 0


# ══════════════════════════════════════════════════════════════════════
# No user message
# ══════════════════════════════════════════════════════════════════════


class TestNoUserMessage:
    @pytest.mark.asyncio
    async def test_active_mode_without_user_message_is_rejected_without_injector_call(
        self,
    ):
        injector = FakeMemoryInjector()
        executor = GatewayExecutor(
            transport=FakeProviderTransport(),
            memory_injector=injector,
        )
        chat = _make_chat((
            ("system", "only system message"),
        ))
        with pytest.raises(GatewayExecutionError, match="user"):
            await executor.execute(chat, _active_plan())
        assert injector.call_count == 0


# ══════════════════════════════════════════════════════════════════════
# No Conductor / no observe
# ══════════════════════════════════════════════════════════════════════


class TestNoConductorImport:
    def test_gateway_does_not_import_conductor(self):
        import mnemostroma.gateway.routes as routes_mod
        with open(routes_mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "conductor" not in src.lower().replace("conductor", "")

    def test_gateway_execution_does_not_call_observe(self):
        import mnemostroma.gateway.execution as exec_mod
        with open(exec_mod.__file__) as f:
            src = f.read()
        assert "observeuser" not in src.lower()
        assert "Conductor" not in src


# ══════════════════════════════════════════════════════════════════════
# ConductorMemoryInjector adapter contract
# ══════════════════════════════════════════════════════════════════════


class TestConductorMemoryInjectorAdapter:
    @pytest.mark.asyncio
    async def test_adapter_returns_only_string_not_block(self):
        from mnemostroma.integration.proxy import MemoryBlock

        class FakeProxy:
            async def inject(
                self, user_message: str, **kw: Any
            ) -> MemoryBlock:
                return MemoryBlock(context=_MEM_XML, tools=[], stats={})

        adapter = ConductorMemoryInjector(FakeProxy(), memory_max_tokens=600)  # type: ignore[arg-type]
        result = await adapter.inject("test message")
        assert isinstance(result, str)
        assert result == _MEM_XML

    @pytest.mark.asyncio
    async def test_adapter_passes_user_message_to_proxy(self):
        class FakeProxy:
            def __init__(self) -> None:
                self.received: str = ""

            async def inject(
                self, user_message: str, **kw: Any
            ) -> Any:
                self.received = user_message
                from mnemostroma.integration.proxy import MemoryBlock
                return MemoryBlock(context="ok", tools=[], stats={})

        proxy = FakeProxy()
        adapter = ConductorMemoryInjector(proxy, memory_max_tokens=600)  # type: ignore[arg-type]
        await adapter.inject("what about retries?")
        assert proxy.received == "what about retries?"

    @pytest.mark.asyncio
    async def test_adapter_passes_max_tokens(self):
        class FakeProxy:
            def __init__(self) -> None:
                self.max_tokens_received: int | None = None

            async def inject(
                self, user_message: str, **kw: Any
            ) -> Any:
                self.max_tokens_received = kw.get("max_tokens")
                from mnemostroma.integration.proxy import MemoryBlock
                return MemoryBlock(context="ok", tools=[], stats={})

        proxy = FakeProxy()
        adapter = ConductorMemoryInjector(proxy, memory_max_tokens=450)  # type: ignore[arg-type]
        await adapter.inject("test")
        assert proxy.max_tokens_received == 450

    @pytest.mark.asyncio
    async def test_adapter_does_not_include_tools(self):
        class FakeProxy:
            def __init__(self) -> None:
                self.include_tools: bool | None = None

            async def inject(
                self, user_message: str, **kw: Any
            ) -> Any:
                self.include_tools = kw.get("include_tools")
                from mnemostroma.integration.proxy import MemoryBlock
                return MemoryBlock(context="ok", tools=[], stats={})

        proxy = FakeProxy()
        adapter = ConductorMemoryInjector(proxy, memory_max_tokens=600)  # type: ignore[arg-type]
        await adapter.inject("test")
        assert proxy.include_tools is False