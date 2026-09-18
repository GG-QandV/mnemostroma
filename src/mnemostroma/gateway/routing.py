# SPDX-License-Identifier: FSL-1.1-MIT
"""ModelRouter: resolves provider_id from request.model per ADR-004.

Client config never references a provider_id — only Gateway base_url.
The model->provider mapping is entirely server-side (gateway.providers
config), keeping client model-picker UIs functional via /v1/models.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatRequest, RoutePlan
from mnemostroma.gateway.dispatch import build_dispatch_plan
from mnemostroma.gateway.errors import ModelNotFoundError
from mnemostroma.gateway.memory_plan import build_memory_plan

if TYPE_CHECKING:
    from mnemostroma.gateway.models import GatewayProfile


def resolve_route(request: ChatRequest, config: GatewayConfig) -> RoutePlan:
    """Legacy route plan builder used by routes.py."""
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


@dataclass(frozen=True)
class ModelRoute:
    provider_id: str
    upstream_model: str
    protocol: Literal["openai", "anthropic", "gemini"]


class ModelRouter:
    """Built once at GatewayServer.start(), rebuilt if config reloads."""

    def __init__(self, providers: dict[str, "GatewayProfile"]) -> None:
        self._index: dict[str, ModelRoute] = {}
        for provider_id, profile in providers.items():
            if not profile.enabled:
                continue
            for model_id in profile.exposed_models:
                if model_id in self._index:
                    continue
                upstream_model = model_id
                prefix = f"{provider_id}/"
                if model_id.startswith(prefix):
                    upstream_model = model_id[len(prefix):]
                self._index[model_id] = ModelRoute(
                    provider_id=provider_id,
                    upstream_model=upstream_model,
                    protocol=profile.protocol,
                )

    def resolve(self, requested_model: str) -> ModelRoute:
        route = self._index.get(requested_model)
        if route is None:
            raise ModelNotFoundError(requested_model)
        return route

    def all_routes(self) -> dict[str, ModelRoute]:
        return dict(self._index)
