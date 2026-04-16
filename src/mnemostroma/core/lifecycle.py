# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
import signal
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mnemostroma.conductor import Conductor

logger = logging.getLogger(__name__)

def register_signal_handlers(conductor: "Conductor") -> None:
    """Register OS signal handlers for graceful shutdown and out-of-band commands."""
    loop = asyncio.get_running_loop()
    
    # We cancel the current task representing the main daemon loop to trigger graceful shutdown.
    main_task = asyncio.current_task()

    if sys.platform != "win32":
        # Unix: add_signal_handler works on SelectorEventLoop
        def handle_termination():
            logger.info("Graceful shutdown triggered via signal.")
            if main_task:
                main_task.cancel()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_termination)

        # SIGUSR1 → flush write queue immediately
        if hasattr(signal, "SIGUSR1"):
            def _on_flush():
                ctx = conductor.ctx
                if ctx and ctx.persistence:
                    asyncio.ensure_future(ctx.persistence.flush())
                    logger.info("SIGUSR1: flush triggered")
            loop.add_signal_handler(signal.SIGUSR1, _on_flush)

        # SIGUSR2 → dump state (Hot/Warm layer)
        if hasattr(signal, "SIGUSR2"):
            def _on_dump():
                ctx = conductor.ctx
                if ctx:
                    from mnemostroma.tools.admin import ctx_dump
                    asyncio.ensure_future(ctx_dump(ctx))
                    logger.info("SIGUSR2: dump triggered")
            loop.add_signal_handler(signal.SIGUSR2, _on_dump)
    else:
        # Windows: ProactorEventLoop does not support add_signal_handler.
        signal.signal(signal.SIGINT, lambda *_: main_task.cancel() if main_task else None)
