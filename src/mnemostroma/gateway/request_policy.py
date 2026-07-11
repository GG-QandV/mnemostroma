# SPDX-License-Identifier: FSL-1.1-MIT
"""Bounded request validation for chat completions.

All violations return ``GatewayParseError`` → HTTP 400 ``invalid_request``.
"""
from __future__ import annotations

from typing import Any

from starlette.requests import Request

from mnemostroma.gateway.contracts import ChatMessage, ChatRequest
from mnemostroma.gateway.errors import GatewayParseError

# ── fixed limits ──────────────────────────────────────────────────────
RAW_BODY_MAX = 1_048_576          # 1 MiB
MAX_MESSAGES = 64
MAX_MODEL_LENGTH = 256
MAX_MESSAGE_CONTENT = 32_768
MAX_TOTAL_CONTENT = 131_072
MAX_SYSTEM_MESSAGES = 8
MAX_USER_MESSAGES = 32
MAX_ASSISTANT_MESSAGES = 32

_ALLOWED_ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})
_ALLOWED_MESSAGE_FIELDS: frozenset[str] = frozenset({"role", "content"})


async def read_bounded_body(
    request: Request,
    max_bytes: int = RAW_BODY_MAX,
) -> bytes:
    total = 0
    chunks: list[bytes] = []
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise GatewayParseError(
                f"request body exceeds {max_bytes} byte limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)


def validate_chat_request(body: dict[str, Any]) -> ChatRequest:
    model = body.get("model")
    if not isinstance(model, str) or not model.strip():
        raise GatewayParseError("model is required")
    if "\x00" in model:
        raise GatewayParseError("model contains NUL")
    if len(model) > MAX_MODEL_LENGTH:
        raise GatewayParseError(
            f"model exceeds {MAX_MODEL_LENGTH} characters"
        )

    raw_messages = body.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise GatewayParseError("messages is required and must be non-empty")
    if len(raw_messages) > MAX_MESSAGES:
        raise GatewayParseError(f"messages exceeds {MAX_MESSAGES}")

    system_count = 0
    user_count = 0
    assistant_count = 0
    total_content = 0
    parsed: list[ChatMessage] = []

    for i, msg in enumerate(raw_messages):
        if not isinstance(msg, dict):
            raise GatewayParseError(f"messages[{i}] must be an object")

        unknown_fields = set(msg.keys()) - _ALLOWED_MESSAGE_FIELDS
        if unknown_fields:
            raise GatewayParseError(
                f"messages[{i}] has unknown fields: {', '.join(sorted(unknown_fields))}"
            )

        role = msg.get("role")
        if role not in _ALLOWED_ROLES:
            raise GatewayParseError(f"messages[{i}].role is invalid")

        content = msg.get("content")
        if not isinstance(content, str):
            raise GatewayParseError(f"messages[{i}].content must be a string")
        if not content or not content.strip():
            raise GatewayParseError(f"messages[{i}].content is empty or blank")
        if "\x00" in content:
            raise GatewayParseError(f"messages[{i}].content contains NUL")
        if len(content) > MAX_MESSAGE_CONTENT:
            raise GatewayParseError(
                f"messages[{i}].content exceeds {MAX_MESSAGE_CONTENT} characters"
            )

        if role == "system":
            system_count += 1
        elif role == "user":
            user_count += 1
        elif role == "assistant":
            assistant_count += 1

        total_content += len(content)
        parsed.append(ChatMessage(role=role, content=content))

    if system_count > MAX_SYSTEM_MESSAGES:
        raise GatewayParseError(f"too many system messages ({MAX_SYSTEM_MESSAGES} max)")
    if user_count > MAX_USER_MESSAGES:
        raise GatewayParseError(f"too many user messages ({MAX_USER_MESSAGES} max)")
    if assistant_count > MAX_ASSISTANT_MESSAGES:
        raise GatewayParseError(
            f"too many assistant messages ({MAX_ASSISTANT_MESSAGES} max)"
        )
    if total_content > MAX_TOTAL_CONTENT:
        raise GatewayParseError(
            f"total message content exceeds {MAX_TOTAL_CONTENT} characters"
        )

    if not any(m.role == "user" for m in parsed):
        raise GatewayParseError("at least one user message is required")

    stream = body.get("stream", False)
    if not isinstance(stream, bool):
        raise GatewayParseError("stream must be a boolean")
    if stream:
        raise GatewayParseError("stream=true is not supported")

    return ChatRequest(
        model=model,
        messages=tuple(parsed),
        stream=False,
    )
