# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal


class FailureMode(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class MemoryMode(StrEnum):
    OFF = "off"
    READ_ONLY = "read_only"
    FULL = "full"


class CaptureMode(StrEnum):
    GATEWAY = "gateway"
    LEGACY_PROXY = "legacy_proxy"
    MITM = "mitm"
    EXTENSION = "extension"
    MCP_ONLY = "mcp_only"


@dataclass(frozen=True)
class GatewayProfile:
    provider_id: str
    protocol: Literal["openai", "anthropic", "gemini", "openai-compatible"]
    base_url: str
    credential_env: str
    allowed_hosts: tuple[str, ...] = ()
    exposed_models: tuple[str, ...] = ()
    enabled: bool = True
    failure_mode: FailureMode = FailureMode.OPEN
    memory_mode: MemoryMode = MemoryMode.READ_ONLY
    capture_mode: CaptureMode = CaptureMode.GATEWAY
    match_client_ids: tuple[str, ...] = ()
    require_client_id_header: bool = False


@dataclass(frozen=True)
class MessagePart:
    type: Literal["text", "image", "tool_use", "tool_result"]
    content: str


@dataclass(frozen=True)
class CanonicalMessage:
    role: Literal["user", "assistant", "system", "tool"]
    parts: tuple[MessagePart, ...]
    tool_call_id: str | None = None
    tool_calls: tuple[dict, ...] | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    parameters_schema: dict


@dataclass(frozen=True)
class UpstreamTarget:
    provider_id: str
    protocol: str
    base_url: str
    credential_ref: str
    allowed_hosts: tuple[str, ...]
    connect_timeout_s: float = 10.0
    first_byte_timeout_s: float = 60.0
    idle_timeout_s: float = 300.0


@dataclass(frozen=True)
class MemoryPolicy:
    mode: Literal["off", "read_only", "full"] = "read_only"
    scope: Literal["global", "workspace", "client", "strict"] = "global"
    inject: bool = True
    observe_user: bool = True
    observe_assistant: bool = True
    max_context_tokens: int = 600
    max_source_sessions: int = 3
    fail_mode: Literal["open", "closed"] = "open"
    allow_partial_capture: bool = True


@dataclass(frozen=True)
class MemoryBlock:
    request_id: str
    conversation_id: str
    text: str
    token_estimate: int
    source_session_ids: tuple[str, ...]
    policy: str
    generated_at: float


@dataclass(frozen=True)
class GatewayRequest:
    request_id: str
    conversation_id: str
    client_id: str
    protocol: Literal["openai", "anthropic", "gemini"]
    provider_id: str
    model: str
    system_parts: tuple[MessagePart, ...]
    messages: tuple[CanonicalMessage, ...]
    stream: bool
    tools: tuple[ToolDefinition, ...]
    upstream: UpstreamTarget
    memory_policy: MemoryPolicy
    project_id: str | None = None
    conversation_id_is_new: bool = False
