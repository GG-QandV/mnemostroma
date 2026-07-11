# SPDX-License-Identifier: FSL-1.1-MIT
"""Gateway memory adapters for ConductorProxy — composition root only.

These adapters live outside ``gateway/`` so they can import from
``integration.proxy`` without leaking ConductorProxy into the Gateway.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.memory_injector import MemoryInjector
from mnemostroma.gateway.observer import CompletionObserver
from mnemostroma.gateway.routes import create_app as _create_app
from mnemostroma.integration.proxy import ConductorProxy


class ConductorProxyMemoryInjector:
    """Wraps ConductorProxy.inject() into the Gateway MemoryInjector port."""

    def __init__(self, proxy: ConductorProxy, max_tokens: int = 600) -> None:
        self._proxy = proxy
        self._max_tokens = max_tokens

    async def inject(self, user_message: str) -> str:
        try:
            block = await self._proxy.inject(
                user_message,
                max_tokens=self._max_tokens,
                include_tools=False,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from mnemostroma.gateway.errors import MemoryUnavailable
            raise MemoryUnavailable(str(exc)) from exc
        return block.context


class ConductorProxyCompletionObserver:
    """Wraps a proxy observation method into the Gateway CompletionObserver port."""

    def __init__(self, proxy: Any) -> None:
        self._proxy = proxy

    async def observe(
        self, *, user_message: str, assistant_message: str
    ) -> None:
        observe_method = getattr(self._proxy, "observe", None)
        if observe_method is not None:
            await observe_method(user_message, assistant_message)


def create_gateway_app(
    *,
    config: GatewayConfig,
    proxy: ConductorProxy | None = None,
) -> Any:
    """Build a fully wired Starlette Gateway app.

    If *proxy* is ``None``, memory injector and completion observer are
    omitted — ``memory_mode="active"`` and ``observation_mode="active"``
    will not work.
    """
    token = os.environ.get(config.token_env, "")
    memory_injector: MemoryInjector | None = None
    completion_observer: CompletionObserver | None = None

    if proxy is not None:
        memory_injector = ConductorProxyMemoryInjector(proxy)
        completion_observer = ConductorProxyCompletionObserver(proxy)

    return _create_app(
        expected_token=token,
        gateway_config=config,
        memory_injector=memory_injector,
        completion_observer=completion_observer,
    )
