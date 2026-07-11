# SPDX-License-Identifier: FSL-1.1-MIT
"""Observation — best-effort background recording of completed exchanges.

The Gateway schedules an observation task after a successful provider
completion.  The observer receives only two strings — the last user
message and the normalized assistant response — and is never awaited
on the hot path.

Lifecycle ownership is handled by ObservationTaskRegistry.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any, Protocol

from mnemostroma.gateway.contracts import ChatRequest

from .metrics import GatewayMetrics

logger = logging.getLogger(__name__)

TaskSpawner = Callable[[Coroutine[Any, Any, None]], asyncio.Task[None]]

_MAX_PENDING = 256
_OBSERVE_TIMEOUT = 2.0
_DRAIN_TIMEOUT = 3.0


class CompletionObserver(Protocol):
    async def observe(
        self,
        *,
        user_message: str,
        assistant_message: str,
    ) -> None: ...


class ObservationTaskRegistry:
    """Owns observation tasks and provides lifecycle drain.

    Lock-free within the event loop (no threads).  Idempotent drain.
    """

    def __init__(
        self,
        spawner: TaskSpawner | None = None,
        metrics: GatewayMetrics | None = None,
    ) -> None:
        self._tasks: set[asyncio.Task[None]] = set()
        self._shutdown_started = False
        self._spawner: TaskSpawner = spawner or asyncio.create_task
        self._metrics = metrics

    def schedule(
        self,
        observer: CompletionObserver,
        user_message: str,
        assistant_message: str,
    ) -> bool:
        if self._shutdown_started:
            return False
        if len(self._tasks) >= _MAX_PENDING:
            logger.warning("Observation backlog full (%s), dropping", _MAX_PENDING)
            return False

        _metrics = self._metrics

        async def _run() -> None:
            try:
                await asyncio.wait_for(
                    observer.observe(
                        user_message=user_message,
                        assistant_message=assistant_message,
                    ),
                    timeout=_OBSERVE_TIMEOUT,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                logger.warning("Observation timed out after %ss", _OBSERVE_TIMEOUT)
            except Exception:
                logger.exception("Observation failed")
                if _metrics is not None:
                    _metrics.increment("gateway_observations_failed_total")
                raise

        task = self._spawner(_run())
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        if self._metrics is not None:
            self._metrics.increment("gateway_observations_scheduled_total")
        return True

    def _task_done(self, task: asyncio.Task[None]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            if self._metrics is not None:
                self._metrics.increment("gateway_observations_cancelled_total")
            return
        exc = task.exception()
        if exc is not None:
            logger.warning(
                "Observation task failed: %s",
                type(exc).__name__,
            )
        else:
            if self._metrics is not None:
                self._metrics.increment("gateway_observations_completed_total")

    async def drain(self, timeout_seconds: float = _DRAIN_TIMEOUT) -> None:
        self._shutdown_started = True
        if not self._tasks:
            return
        _, pending = await asyncio.wait(
            self._tasks,
            timeout=timeout_seconds,
            return_when=asyncio.ALL_COMPLETED,
        )
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        self._tasks.clear()


def schedule_observation(
    observer: CompletionObserver,
    user_message: str,
    assistant_message: str,
    registry: ObservationTaskRegistry,
) -> bool:
    return registry.schedule(observer, user_message, assistant_message)


def last_user_content(chat_request: ChatRequest) -> str | None:
    for msg in reversed(chat_request.messages):
        if msg.role == "user":
            return msg.content
    return None


def assistant_content(completion: dict[str, Any]) -> str | None:
    choices = completion.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    msg = choice.get("message")
    if not isinstance(msg, dict):
        return None
    content = msg.get("content")
    return str(content) if content is not None else None
