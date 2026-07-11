# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from mnemostroma.gateway.contracts import ChatMessage, ChatRequest
from mnemostroma.gateway.errors import GatewayParseError

_ALLOWED_TOP_LEVEL: frozenset[str] = frozenset({
    "model", "messages", "stream", "temperature", "max_tokens",
})

_ALLOWED_ROLES: frozenset[str] = frozenset({"system", "user", "assistant"})

_ALLOWED_MESSAGE_FIELDS: frozenset[str] = frozenset({"role", "content"})

_UNSUPPORTED_FIELDS: frozenset[str] = frozenset({
    "tools", "tool_choice", "functions", "function_call",
    "response_format", "seed", "n", "logprobs", "modalities", "audio",
})


def parse_chat_completions(payload: object) -> ChatRequest:
    if not isinstance(payload, dict):
        raise GatewayParseError(
            "request body must be a JSON object"
        )

    _check_unsupported_fields(payload)

    model = payload.get("model")
    if not isinstance(model, str) or not model.strip():
        raise GatewayParseError("'model' is required and must be a non-empty string")

    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list) or len(raw_messages) == 0:
        raise GatewayParseError(
            "'messages' is required and must be a non-empty array"
        )

    messages = tuple(_parse_message(i, m) for i, m in enumerate(raw_messages))

    stream = payload.get("stream", False)
    if not isinstance(stream, bool):
        raise GatewayParseError("'stream' must be a boolean")

    temperature = payload.get("temperature")
    if temperature is not None:
        if not isinstance(temperature, (int, float)):
            raise GatewayParseError("'temperature' must be a number")
        temperature = float(temperature)
        if not (0.0 <= temperature <= 2.0):
            raise GatewayParseError(
                "'temperature' must be between 0 and 2"
            )

    max_tokens = payload.get("max_tokens")
    if max_tokens is not None and (not isinstance(max_tokens, int) or max_tokens <= 0):
        raise GatewayParseError(
            "'max_tokens' must be a positive integer"
        )

    _check_unknown_top_level(payload)

    return ChatRequest(
        model=model.strip(),
        messages=messages,
        stream=stream,
        temperature=temperature,
        max_tokens=max_tokens,
    )


def _check_unsupported_fields(payload: dict) -> None:
    for field in _UNSUPPORTED_FIELDS:
        if field in payload:
            raise GatewayParseError(
                f"'{field}' is not supported by Gateway dry-run mode"
            )


def _check_unknown_top_level(payload: dict) -> None:
    for key in payload:
        if key not in _ALLOWED_TOP_LEVEL and key not in _UNSUPPORTED_FIELDS:
            raise GatewayParseError(
                f"'{key}' is not a recognized field"
            )


def _parse_message(index: int, msg: object) -> ChatMessage:
    if not isinstance(msg, dict):
        raise GatewayParseError(
            f"messages[{index}] must be an object"
        )

    for key in msg:
        if key not in _ALLOWED_MESSAGE_FIELDS:
            raise GatewayParseError(
                f"messages[{index}] contains unsupported field '{key}'"
            )

    role = msg.get("role")
    if role not in _ALLOWED_ROLES:
        raise GatewayParseError(
            f"messages[{index}].role must be one of {sorted(_ALLOWED_ROLES)}"
        )

    content = msg.get("content")
    if content is None:
        raise GatewayParseError(
            f"messages[{index}].content is required"
        )
    if isinstance(content, list):
        raise GatewayParseError(
            f"messages[{index}].content must be a string, not an array"
        )
    if not isinstance(content, str):
        raise GatewayParseError(
            f"messages[{index}].content must be a string"
        )

    return ChatMessage(role=role, content=content)
