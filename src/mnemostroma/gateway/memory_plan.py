# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.contracts import ChatRequest, MemoryPlan


def build_memory_plan(
    request: ChatRequest,
    config: GatewayConfig,
) -> MemoryPlan:
    if config.memory_mode not in ("planned", "active"):
        return MemoryPlan(mode="off", would_inject=False)

    source_index: int | None = None
    for i, msg in enumerate(request.messages):
        if msg.role == "user":
            source_index = i

    would_inject = source_index is not None
    mode = config.memory_mode

    return MemoryPlan(
        mode=mode,
        would_inject=would_inject,
        would_observe=False,
        source_message_index=source_index,
        max_tokens=config.memory_max_tokens,
    )