# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import inspect

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatMessage, ChatRequest
from mnemostroma.gateway.routing import resolve_route


class TestRoutePlan:
    def test_route_plan_is_deterministic(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        plan1 = resolve_route(req, cfg)
        plan2 = resolve_route(req, cfg)
        assert plan1.id == plan2.id
        assert plan1.id.startswith("gwplan_")

    def test_different_requests_different_ids(self):
        cfg = GatewayConfig(enabled=True)
        req1 = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        req2 = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="world")],
        )
        assert resolve_route(req1, cfg).id != resolve_route(req2, cfg).id

    def test_route_plan_has_correct_structure(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="claude-3",
            messages=[ChatMessage(role="user", content="hi")],
            stream=True,
        )
        plan = resolve_route(req, cfg)
        assert plan.object == "mnemo.gateway.route_plan"
        assert plan.dry_run is True
        assert plan.execution == "not_dispatched"
        assert plan.provider_name == "openai_compatible"
        assert plan.model == "claude-3"
        assert plan.upstream_path == "/v1/chat/completions"
        assert plan.stream is True

    def test_route_plan_stream_default_off(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        plan = resolve_route(req, cfg)
        assert plan.stream is False

    def test_route_plan_has_created_timestamp(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        plan = resolve_route(req, cfg)
        assert isinstance(plan.created, int)
        assert plan.created > 0


class TestMemoryContract:
    def test_route_plan_has_no_memory_side_effect(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        plan = resolve_route(req, cfg)
        assert plan.memory.would_inject is False
        assert plan.memory.would_observe is False

    def test_route_plan_does_not_expose_token_or_provider_secret(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hi")],
        )
        plan = resolve_route(req, cfg)
        plan_str = str(plan.__dict__) + str(plan.id)
        assert "sk-" not in plan_str
        lower = plan_str.lower()
        assert "api_key" not in lower
        assert "secret" not in lower
        assert "bearer" not in lower

    def test_route_plan_does_not_contain_message_content(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="my-secret-message")],
        )
        plan = resolve_route(req, cfg)
        plan_str = str(plan.__dict__)
        assert "my-secret-message" not in plan_str


class TestDryRunSafety:
    def test_dry_run_never_imports_httpx(self):
        import mnemostroma.gateway.routing as routing_mod
        with open(routing_mod.__file__) as f:
            src = f.read()
        assert "httpx" not in src, "routing should not import httpx"

    def test_dry_run_never_imports_conductor(self):
        import mnemostroma.gateway.routing as routing_mod
        with open(routing_mod.__file__) as f:
            src = f.read()
        assert "Conductor" not in src
        assert "conductor" not in src.lower()

    def test_dry_run_never_imports_proxy(self):
        import mnemostroma.gateway.routing as routing_mod
        with open(routing_mod.__file__) as f:
            src = f.read()
        assert "ConductorProxy" not in src
        assert "Proxy" not in src

    def test_resolve_route_is_pure_sync(self):
        from mnemostroma.gateway.routing import resolve_route
        assert not inspect.iscoroutinefunction(resolve_route)

    def test_resolve_route_does_not_call_observe_or_inject(self):
        cfg = GatewayConfig(enabled=True)
        req = ChatRequest(
            model="gpt-4",
            messages=[ChatMessage(role="user", content="hello")],
        )
        plan = resolve_route(req, cfg)
        assert plan.execution == "not_dispatched"
        assert plan.memory.would_inject is False
        assert plan.memory.would_observe is False


class TestOpenAIParserIsSync:
    def test_parse_is_pure_sync(self):
        from mnemostroma.gateway.openai import parse_chat_completions
        assert not inspect.iscoroutinefunction(parse_chat_completions)
