# SPDX-License-Identifier: FSL-1.1-MIT
"""Narrow memory injection port for the Gateway.

The Gateway knows only about ``MemoryInjector`` — a Protocol returning ``str``.
The ``ConductorMemoryInjector`` adapter wraps ``ConductorProxy`` (duck-typed)
and extracts ``MemoryBlock.context`` so the Gateway never sees proxy internals.
"""
from __future__ import annotations

from typing import Any, Protocol


class MemoryInjector(Protocol):
    async def inject(self, user_message: str) -> str: ...


class ConductorMemoryInjector:
    """Adapter wrapping ConductorProxy into the narrow MemoryInjector port.

    ``proxy`` is duck-typed — no import of ConductorProxy needed.
    The Gateway receives only an ``str`` from ``inject``.
    """

    def __init__(
        self,
        proxy: Any,
        memory_max_tokens: int = 600,
    ) -> None:
        self._proxy = proxy
        self._max_tokens = memory_max_tokens

    async def inject(self, user_message: str) -> str:
        block = await self._proxy.inject(
            user_message,
            max_tokens=self._max_tokens,
            include_tools=False,
        )
        context = getattr(block, "context", "")
        if not isinstance(context, str):
            raise TypeError(
                "ConductorMemoryInjector: proxy returned non-string context"
            )
        return context


__all__ = [
    "MemoryInjector",
    "ConductorMemoryInjector",
]