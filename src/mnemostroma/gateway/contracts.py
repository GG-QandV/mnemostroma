# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ChatMessage:
    role: str
    content: str


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    stream: bool = False
    temperature: float | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class MemoryPlan:
    mode: Literal["off", "planned", "active"]
    would_inject: bool
    would_observe: bool = False
    source_message_index: int | None = None
    max_tokens: int | None = None


@dataclass(frozen=True)
class ProviderPlan:
    mode: Literal["disabled", "configured"]
    would_dispatch: bool
    upstream_path: str | None = None


@dataclass(frozen=True)
class RoutePlan:
    id: str
    object: str = "mnemo.gateway.route_plan"
    created: int = 0
    dry_run: bool = True
    execution: str = "not_dispatched"
    reason: str | None = None
    provider_name: str = "openai_compatible"
    model: str = ""
    upstream_path: str = "/v1/chat/completions"
    stream: bool = False
    memory: MemoryPlan = field(default_factory=lambda: MemoryPlan(
        mode="off", would_inject=False,
    ))
    provider: ProviderPlan = field(default_factory=lambda: ProviderPlan(
        mode="disabled", would_dispatch=False,
    ))
