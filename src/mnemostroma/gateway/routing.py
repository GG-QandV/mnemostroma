# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import hashlib
import time

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatRequest, RoutePlan
from mnemostroma.gateway.dispatch import build_dispatch_plan
from mnemostroma.gateway.memory_plan import build_memory_plan


def resolve_route(request: ChatRequest, config: GatewayConfig) -> RoutePlan:
    canonical = _canonical(request)
    plan_id = "gwplan_" + hashlib.sha256(canonical.encode()).hexdigest()[:24]
    memory = build_memory_plan(request, config)
    dispatch = build_dispatch_plan(config)

    execution = "not_dispatched"
    reason: str | None = None
    if dispatch.mode == "configured":
        execution = "blocked"
        reason = "provider_dispatch_not_enabled"

    return RoutePlan(
        id=plan_id,
        object="mnemo.gateway.route_plan",
        created=int(time.time()),
        dry_run=True,
        execution=execution,
        reason=reason,
        provider_name="openai_compatible",
        model=request.model,
        upstream_path="/v1/chat/completions",
        stream=request.stream,
        memory=memory,
        provider=dispatch,
    )


def _canonical(request: ChatRequest) -> str:
    parts: list[str] = []
    parts.append(f"model={request.model}")
    for m in request.messages:
        parts.append(f"msg:{m.role}={m.content}")
    parts.append(f"stream={request.stream}")
    if request.temperature is not None:
        parts.append(f"temp={request.temperature}")
    if request.max_tokens is not None:
        parts.append(f"maxtok={request.max_tokens}")
    return "|".join(parts)
