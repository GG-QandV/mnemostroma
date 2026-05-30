# SPDX-License-Identifier: FSL-1.1-MIT
"""Circuit Breaker for IPC calls.

States:
  CLOSED    — normal, calls pass through
  OPEN      — after N errors, bypass for T seconds (fail-open)
  HALF_OPEN — trial call after timeout
"""
import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from enum import Enum
from typing import Any

logger = logging.getLogger("mnemostroma.circuit_breaker")


class State(Enum):
    CLOSED    = "closed"
    OPEN      = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        name: str,
        failure_threshold: int   = 3,    # errors before OPEN
        recovery_timeout:  float = 30.0, # seconds in OPEN
        half_open_timeout: float = 5.0,  # trial call timeout
    ):
        self.name        = name
        self._threshold  = failure_threshold
        self._recovery   = recovery_timeout
        self._ho_timeout = half_open_timeout
        self._state      = State.CLOSED
        self._failures   = 0
        self._opened_at: float | None = None

    @property
    def state(self) -> State:
        if self._state == State.OPEN:
            if time.monotonic() - self._opened_at >= self._recovery:
                self._state = State.HALF_OPEN
                logger.info(f"Circuit [{self.name}]: OPEN → HALF_OPEN")
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state == State.OPEN

    async def call(
        self,
        fn: Callable[..., Coroutine],
        *args,
        fallback: Any = None,
        **kwargs,
    ) -> Any:
        s = self.state
        if s == State.OPEN:
            logger.debug(f"Circuit [{self.name}] OPEN — returning fallback")
            return fallback
        try:
            if s == State.HALF_OPEN:
                result = await asyncio.wait_for(
                    fn(*args, **kwargs), timeout=self._ho_timeout
                )
            else:
                result = await fn(*args, **kwargs)
            # Success — reset counter
            if self._state != State.CLOSED:
                logger.info(f"Circuit [{self.name}]: → CLOSED")
            self._state    = State.CLOSED
            self._failures = 0
            return result
        except Exception as e:
            self._failures += 1
            logger.warning(
                f"Circuit [{self.name}] failure "
                f"{self._failures}/{self._threshold}: {e}"
            )
            if self._failures >= self._threshold:
                self._state     = State.OPEN
                self._opened_at = time.monotonic()
                logger.error(
                    f"Circuit [{self.name}]: → OPEN for {self._recovery}s"
                )
            return fallback  # always fail-open: return fallback, don't raise
