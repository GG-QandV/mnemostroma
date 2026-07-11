# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from mnemostroma.gateway.contracts import ChatRequest, MemoryPlan
from mnemostroma.gateway.provider import ProviderRequest


def materialize_provider_request(
    chat_request: ChatRequest,
    memory: MemoryPlan,
    injected_context: str | None = None,
) -> ProviderRequest:
    base_messages = tuple(
        {"role": m.role, "content": m.content}
        for m in chat_request.messages
    )

    if injected_context is not None:
        insert_at = 0
        for m in chat_request.messages:
            if m.role == "system":
                insert_at += 1
            else:
                break
        memory_msg = {"role": "system", "content": injected_context}
        base_messages = (
            base_messages[:insert_at]
            + (memory_msg,)
            + base_messages[insert_at:]
        )

    injection_state = (
        "injected" if injected_context is not None else "not_materialized"
    )

    return ProviderRequest(
        model=chat_request.model,
        messages=base_messages,
        stream=chat_request.stream,
        temperature=chat_request.temperature,
        max_tokens=chat_request.max_tokens,
        memory_injection=injection_state,
    )