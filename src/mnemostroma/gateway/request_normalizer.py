# SPDX-License-Identifier: FSL-1.1-MIT
"""RequestNormalizer: builds canonical GatewayRequest from raw protocol
input, per Gateway spec v1.0 "Request normalizer" section.

Invariants enforced here (spec-mandated):
- conversation_id is derived from a stable ID, never from prompt text
  alone (would collide identical prompts across different sessions).
- client_id comes from header / profile config, never from user message.
- Control characters are stripped; prompt/tool-argument/binary semantics
  are never altered.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

from mnemostroma.gateway.errors import InvalidClientIdError
from mnemostroma.gateway.models import (
    CanonicalMessage,
    GatewayProfile,
    GatewayRequest,
    MemoryPolicy,
    MessagePart,
    ToolDefinition,
    UpstreamTarget,
)

_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _strip_control_chars(text: str) -> str:
    """Remove invalid control characters without altering semantic content.
    Preserves \\n (0x0a) and \\t (0x09) — these are meaningful in prompts.
    """
    return _CONTROL_CHAR_RE.sub("", text)


def resolve_client_id(
    headers: dict[str, str],
    profile: "GatewayProfile",
) -> str:
    """Resolve client_id: header > profile default > 'unknown'.

    Never derived from user message body (spec invariant). See ADR
    discussion: header takes precedence to disambiguate multiple CLIs
    sharing one bearer token; falls back gracefully unless the profile
    explicitly requires strict header presence (regulated profiles).
    """
    header_value = headers.get("x-mnemo-client-id", "").strip()
    if header_value:
        return _strip_control_chars(header_value)

    if profile.require_client_id_header:
        raise InvalidClientIdError(
            "X-Mnemo-Client-Id header is required by this profile"
        )

    if profile.match_client_ids:
        return profile.match_client_ids[0]

    return "unknown"


def derive_conversation_id(
    *,
    client_provided_id: str | None,
    client_id: str,
    workspace_id: str | None,
    provider_conversation_id: str | None,
) -> tuple[str, bool]:
    """Derive conversation_id per spec priority order.

    Returns (conversation_id, is_newly_generated).

    Priority:
    1. client_provided_id (stable, client-supplied) — highest priority.
    2. client_id + workspace_id + provider_conversation_id composite.
    3. New UUID — only when none of the above are available; caller
       must return this new ID in response headers.

    NEVER built from prompt text alone (spec invariant) — that risks
    merging distinct sessions that happen to share the same first
    message.
    """
    if client_provided_id:
        return _strip_control_chars(client_provided_id.strip()), False

    composite_parts = [
        p for p in (client_id, workspace_id, provider_conversation_id) if p
    ]
    if len(composite_parts) >= 2:
        composite = "/".join(_strip_control_chars(p) for p in composite_parts)
        return composite, False

    return str(uuid.uuid4()), True


def _build_message_parts(raw_content: Any) -> tuple[MessagePart, ...]:
    """Normalize OpenAI-style content (str or list-of-blocks) into parts."""
    if isinstance(raw_content, str):
        return (MessagePart(type="text", content=_strip_control_chars(raw_content)),)

    if isinstance(raw_content, list):
        parts: list[MessagePart] = []
        for block in raw_content:
            block_type = block.get("type", "text")
            if block_type == "text":
                parts.append(MessagePart(
                    type="text",
                    content=_strip_control_chars(block.get("text", "")),
                ))
            elif block_type == "image_url":
                parts.append(MessagePart(
                    type="image",
                    content=block.get("image_url", {}).get("url", ""),
                ))
            elif block_type == "tool_use":
                parts.append(MessagePart(type="tool_use", content=str(block)))
            elif block_type == "tool_result":
                parts.append(MessagePart(type="tool_result", content=str(block)))
        return tuple(parts)

    return ()


def normalize_openai_request(
    *,
    body: dict[str, Any],
    headers: dict[str, str],
    provider_id: str,
    upstream: UpstreamTarget,
    profile: "GatewayProfile",
    memory_policy: MemoryPolicy,
    model_override: str | None = None,
) -> GatewayRequest:
    """Build a canonical GatewayRequest from an OpenAI-style chat completions body."""
    request_id = str(uuid.uuid4())

    client_id = resolve_client_id(headers, profile)

    conversation_id, is_new_conversation = derive_conversation_id(
        client_provided_id=headers.get("x-mnemo-conversation-id"),
        client_id=client_id,
        workspace_id=headers.get("x-mnemo-workspace-id"),
        provider_conversation_id=body.get("conversation_id") or body.get("user"),
    )

    raw_messages = body.get("messages", [])
    system_parts: list[MessagePart] = []
    canonical_messages: list[CanonicalMessage] = []

    for raw_msg in raw_messages:
        role = raw_msg.get("role", "user")
        parts = _build_message_parts(raw_msg.get("content", ""))
        raw_tool_calls = raw_msg.get("tool_calls")
        if role == "system":
            system_parts.extend(parts)
        else:
            canonical_messages.append(CanonicalMessage(
                role=role,
                parts=parts,
                tool_call_id=raw_msg.get("tool_call_id"),
                tool_calls=tuple(raw_tool_calls) if raw_tool_calls else None,
            ))

    tools = tuple(
        ToolDefinition(
            name=t.get("function", {}).get("name", ""),
            description=t.get("function", {}).get("description", ""),
            parameters_schema=t.get("function", {}).get("parameters", {}),
        )
        for t in body.get("tools", [])
    )

    return GatewayRequest(
        request_id=request_id,
        conversation_id=conversation_id,
        client_id=client_id,
        protocol="openai",
        provider_id=provider_id,
        model=model_override or body.get("model", ""),
        system_parts=tuple(system_parts),
        messages=tuple(canonical_messages),
        stream=bool(body.get("stream", False)),
        tools=tools,
        upstream=upstream,
        memory_policy=memory_policy,
        conversation_id_is_new=is_new_conversation,
    )
