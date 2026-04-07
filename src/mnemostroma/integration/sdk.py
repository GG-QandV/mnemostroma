# SPDX-License-Identifier: FSL-1.1-MIT
"""Mnemostroma Orchestrator SDK.

For orchestrators that manage the LLM call loop. Call build_memory_context()
BEFORE invoking the agent — inject the result into the system prompt.
The agent receives memory as context, not as a tool result.

Usage:
    from mnemostroma.conductor import Conductor
    from mnemostroma.integration.sdk import build_memory_context

    conductor = Conductor()
    await conductor.start(...)

    xml = await build_memory_context(user_message, conductor.ctx)
    system_prompt = BASE_SYSTEM_PROMPT + "\\n" + xml
    response = await llm.call(system=system_prompt, ...)
"""
from typing import TYPE_CHECKING

from .proxy import ConductorProxy

if TYPE_CHECKING:
    from ..core import SystemContext


async def build_memory_context(
    user_message: str,
    ctx: "SystemContext",
    max_tokens: int = 600,
) -> str:
    """Build <memory_context> XML for injection into the system prompt.

    Args:
        user_message: Latest user message — used for semantic search relevance.
        ctx: Live SystemContext from a started Conductor.
        max_tokens: Approximate token budget for the context block.

    Returns:
        XML string ready for system prompt injection.
    """
    proxy = ConductorProxy(ctx)
    block = await proxy.inject(user_message, max_tokens=max_tokens, include_tools=False)
    return block.context
