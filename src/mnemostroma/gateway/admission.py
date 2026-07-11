# SPDX-License-Identifier: FSL-1.1-MIT
"""Admission control for bounded concurrent provider dispatch."""
from __future__ import annotations

import asyncio
from typing import Any


class DispatchPermit:
    __slots__ = ("_admission", "_memory_active")

    def __init__(self, admission: DispatchAdmission, memory_active: bool) -> None:
        self._admission = admission
        self._memory_active = memory_active

    async def __aenter__(self) -> DispatchPermit:
        return self

    async def __aexit__(self, *args: Any) -> None:
        self._admission._release(self._memory_active)


class DispatchAdmission:
    """Bounded admission for concurrent provider dispatch.

    Queue‑free: if a slot is unavailable ``try_acquire`` returns ``None``
    immediately.  A ``DispatchPermit`` (async context manager) releases
    the slot exactly once.
    """

    def __init__(self, max_total: int = 8, max_memory: int = 2) -> None:
        self._max_total = max_total
        self._max_memory = max_memory
        self._current_total = 0
        self._current_memory = 0
        self._lock = asyncio.Lock()

    async def try_acquire(
        self, *, memory_active: bool
    ) -> DispatchPermit | None:
        async with self._lock:
            if self._current_total >= self._max_total:
                return None
            if memory_active and self._current_memory >= self._max_memory:
                return None
            self._current_total += 1
            if memory_active:
                self._current_memory += 1
        return DispatchPermit(self, memory_active)

    def _release(self, memory_active: bool) -> None:
        self._current_total -= 1
        if memory_active:
            self._current_memory -= 1
