# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mnemostroma.conductor import Conductor

logger = logging.getLogger(__name__)

async def run_background_workers(conductor: "Conductor") -> None:
    """
    Orchestrate background workers using a TaskGroup.
    This function blocks until the daemon is stopped.
    """
    async with asyncio.TaskGroup() as tg:
        logger.info("Starting background workers TaskGroup...")

        from mnemostroma.ipc_server import IPCServer
        ipc = IPCServer(conductor)
        tg.create_task(ipc.serve(), name="ipc_server")

        # Embedded SSE server — starts inside daemon, no separate process needed
        sse_cfg = getattr(getattr(conductor, "ctx", None) and conductor.ctx.config, "sse", None)
        if sse_cfg is None:
            from mnemostroma.config import SseConfig
            sse_cfg = SseConfig()
        if sse_cfg.autostart:
            from mnemostroma.integration.mcp_http_adapter import is_port_in_use
            if is_port_in_use(sse_cfg.port, sse_cfg.host):
                logger.warning(
                    "Port %s already in use — embedded SSE not started. "
                    "Stop any standalone 'mnemostroma sse' process first.",
                    sse_cfg.port,
                )
            else:
                from mnemostroma.integration.mcp_sse_adapter import run as _sse_run
                sse_task = tg.create_task(
                    _sse_run(
                        conductor=conductor,
                        port=sse_cfg.port,
                        port_ext=sse_cfg.port_extension,
                        host=sse_cfg.host,
                    ),
                    name="mcp-sse-server",
                )
                conductor._sse_task = sse_task
                logger.info(
                    "Embedded MCP SSE server starting on %s:%s", sse_cfg.host, sse_cfg.port
                )

        # Embedded HTTP server (Streamable HTTP — основной транспорт)
        http_cfg = getattr(getattr(conductor, "ctx", None) and conductor.ctx.config, "http", None)
        if http_cfg is None:
            from mnemostroma.config import HttpConfig
            http_cfg = HttpConfig()
        if http_cfg.autostart:
            from mnemostroma.integration.mcp_http_adapter import is_port_in_use, run as _http_run
            if is_port_in_use(http_cfg.port, http_cfg.host):
                logger.warning(
                    "Port %s already in use — embedded HTTP not started. "
                    "Stop any standalone 'mnemostroma http' process first.",
                    http_cfg.port,
                )
            else:
                http_task = tg.create_task(
                    _http_run(
                        conductor=conductor,
                        port=http_cfg.port,
                        host=http_cfg.host,
                    ),
                    name="mcp-http-server",
                )
                conductor._http_task = http_task
                logger.info(
                    "Embedded MCP HTTP server starting on %s:%s", http_cfg.host, http_cfg.port
                )

        logger.info("Daemon is running. Press Ctrl+C to stop.")

        while True:
            await asyncio.sleep(86400)
