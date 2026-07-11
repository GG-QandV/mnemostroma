# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import inspect

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest
from mnemostroma.gateway.memory_plan import build_memory_plan


class TestMemoryPlanOff:
    def test_memory_plan_off_by_default(self):
        cfg = GatewayConfig()
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        plan = build_memory_plan(req, cfg)
        assert plan.mode == "off"
        assert plan.would_inject is False
        assert plan.would_observe is False
        assert plan.source_message_index is None
        assert plan.max_tokens is None

    def test_memory_plan_off_does_not_select_message(self):
        cfg = GatewayConfig(memory_mode="off")
        req = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="user", content="hello"),
            ],
        )
        plan = build_memory_plan(req, cfg)
        assert plan.source_message_index is None


class TestMemoryPlanPlanned:
    def test_memory_plan_planned_selects_last_user_message(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="user", content="first"),
                ChatMessage(role="assistant", content="ok"),
                ChatMessage(role="user", content="second"),
            ],
        )
        plan = build_memory_plan(req, cfg)
        assert plan.mode == "planned"
        assert plan.would_inject is True
        assert plan.would_observe is False
        assert plan.source_message_index == 3
        assert plan.max_tokens == 600

    def test_memory_plan_ignores_system_and_assistant_messages(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="system", content="be helpful"),
                ChatMessage(role="assistant", content="ok"),
            ],
        )
        plan = build_memory_plan(req, cfg)
        assert plan.mode == "planned"
        assert plan.would_inject is False
        assert plan.source_message_index is None

    def test_memory_plan_without_user_message_is_not_injectable(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(
            model="gpt-4",
            messages=[
                ChatMessage(role="system", content="be helpful"),
            ],
        )
        plan = build_memory_plan(req, cfg)
        assert plan.would_inject is False
        assert plan.source_message_index is None
        assert plan.max_tokens == 600

    def test_memory_plan_uses_configured_max_tokens(self):
        cfg = GatewayConfig(memory_mode="planned", memory_max_tokens=300)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        plan = build_memory_plan(req, cfg)
        assert plan.max_tokens == 300

    def test_memory_plan_is_deterministic(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        plan1 = build_memory_plan(req, cfg)
        plan2 = build_memory_plan(req, cfg)
        assert plan1 == plan2

    def test_memory_plan_empty_when_no_user_message(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(model="gpt-4", messages=[])
        plan = build_memory_plan(req, cfg)
        assert plan.would_inject is False
        assert plan.source_message_index is None


class TestMemoryPlanInRoute:
    def test_route_plan_contains_safe_memory_metadata_only(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="my secret data")],
        )
        from mnemostroma.gateway.routing import resolve_route

        plan = resolve_route(req, cfg)
        memory = plan.memory
        assert memory.mode == "planned"
        assert memory.would_inject is True
        assert memory.would_observe is False
        assert isinstance(memory.source_message_index, int)
        assert isinstance(memory.max_tokens, int)

    def test_route_plan_contains_no_prompt_content(self):
        cfg = GatewayConfig(memory_mode="planned")
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="my secret data")],
        )
        from mnemostroma.gateway.routing import resolve_route

        plan = resolve_route(req, cfg)
        text = str(plan.__dict__)
        assert "my secret data" not in text
        assert "secret" not in text.lower()


class TestMemoryPlanPurity:
    def test_memory_planning_does_not_import_conductor_or_proxy(self):
        import mnemostroma.gateway.memory_plan as mp_mod
        with open(mp_mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "conductor" not in src.lower()
        assert "ConductorProxy" not in src
        assert "Proxy" not in src
        assert "httpx" not in src

    def test_memory_planning_is_pure_sync(self):
        assert not inspect.iscoroutinefunction(build_memory_plan)
