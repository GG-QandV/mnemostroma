# SPDX-License-Identifier: FSL-1.1-MIT
from __future__ import annotations

import asyncio
import logging

from mnemostroma.gateway.config import GatewayConfig
from mnemostroma.gateway.errors import GatewayStartupError

logger = logging.getLogger("mnemostroma.gateway.server")


class GatewayServer:
    def __init__(self, config: GatewayConfig) -> None:
        self.config = config
        self.server: object = None
        self.task: asyncio.Task | None = None
        self._started = asyncio.Event()
        self._shutdown_timeout: float = 5.0

    @property
    def started(self) -> bool:
        return self._started.is_set()

    async def start(self) -> None:
        if not self.config.enabled:
            logger.info("Gateway disabled, skipping start.")
            return

        from mnemostroma.gateway.auth import resolve_token
        from mnemostroma.gateway.routes import create_app

        token = resolve_token(self.config)
        app = create_app(token, gateway_config=self.config)

        import uvicorn

        uv_config = uvicorn.Config(
            app=app,
            host=self.config.host,
            port=self.config.port,
            log_level="info",
        )
        self.server = uvicorn.Server(uv_config)
        self.server.install_signal_handlers = False

        original_startup = self.server.startup

        async def _safe_startup(sockets: object = None) -> None:
            try:
                await original_startup(sockets=sockets)
            except (OSError, SystemExit, GatewayStartupError):
                raise GatewayStartupError(
                    f"failed to bind {self.config.host}:{self.config.port}"
                ) from None

        self.server.startup = _safe_startup  # type: ignore[method-assign]

        self.task = asyncio.create_task(self.server.serve())

        while not self.server.started:
            if self.task.done():
                exc = self.task.exception()
                if isinstance(exc, GatewayStartupError):
                    raise exc
                raise GatewayStartupError(
                    f"failed to bind {self.config.host}:{self.config.port}"
                ) from exc
            await asyncio.sleep(0.01)

        self._started.set()
        logger.info(
            "Gateway server started on %s:%s",
            self.config.host,
            self.config.port,
        )

    async def stop(self) -> None:
        if not self._started.is_set():
            return

        if self.server:
            self.server.should_exit = True

        if self.task and not self.task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self.task), timeout=self._shutdown_timeout
                )
            except TimeoutError:
                logger.warning("Gateway server stop timed out, cancelling.")
                self.task.cancel()
                import contextlib
                with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                    await self.task

        self._started.clear()
        logger.info("Gateway server stopped.")
