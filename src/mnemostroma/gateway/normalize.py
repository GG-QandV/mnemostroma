# SPDX-License-Identifier: FSL-1.1-MIT
"""Normalize upstream provider completions into a stable Gateway response."""
from __future__ import annotations

import secrets
import time
from collections.abc import Callable
from typing import Any

from mnemostroma.gateway.provider_errors import ProviderTransportError

_CONTENT_CAP = 100_000
_ALLOWED_FINISH_REASONS = frozenset({"stop", "length", "content_filter"})


def normalize_completion(
    body: dict[str, Any],
    requested_model: str,
    *,
    clock: Callable[[], float] | None = None,
    id_factory: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Produce a stable, validated Gateway-normalized completion dict.

    Raises ``ProviderTransportError`` (code ``provider_invalid_response``,
    status 502) if the upstream body cannot produce a valid response.
    """
    if clock is None:
        clock = time.time
    if id_factory is None:
        def _default_id() -> str:
            return f"chatcmpl_mnemo_{secrets.token_urlsafe(12)}"
        id_factory = _default_id

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response missing or empty choices",
        )

    choice = choices[0]
    if not isinstance(choice, dict):
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response choice is not an object",
        )

    msg = choice.get("message")
    if not isinstance(msg, dict):
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response message is missing or not an object",
        )

    content = msg.get("content")
    if not isinstance(content, str) or not content.strip():
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response content missing, null, or empty",
        )
    if "\x00" in content:
        raise ProviderTransportError(
            502, "provider_invalid_response",
            "upstream response content contains NUL",
        )
    if len(content) > _CONTENT_CAP:
        raise ProviderTransportError(
            502, "provider_invalid_response",
            f"upstream response content exceeds {_CONTENT_CAP} character cap",
        )

    finish_reason = choice.get("finish_reason")
    if finish_reason not in _ALLOWED_FINISH_REASONS:
        finish_reason = "stop"

    usage_raw = body.get("usage")
    if isinstance(usage_raw, dict):
        p = usage_raw.get("prompt_tokens", 0)
        c = usage_raw.get("completion_tokens", 0)
        prompt_tokens = p if isinstance(p, int) and p >= 0 else 0
        completion_tokens = c if isinstance(c, int) and c >= 0 else 0
    else:
        prompt_tokens = 0
        completion_tokens = 0

    return {
        "id": id_factory(),
        "object": "chat.completion",
        "created": int(clock()),
        "model": requested_model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content,
                },
                "finish_reason": finish_reason,
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
