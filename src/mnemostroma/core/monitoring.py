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
        
        # 1. IPC Server
        from mnemostroma.ipc_server import IPCServer
        ipc = IPCServer(conductor)
        tg.create_task(ipc.serve(), name="ipc_server")
        
        # Note: consolidation_worker, dreamer_worker, watchdog_worker 
        # are currently managed by Conductor.start(). 
        # In future phases, their orchestration may move here fully.
        
        logger.info("Daemon is running. Press Ctrl+C to stop.")
        
        # Infinite loop to keep the TaskGroup alive as requested.
        while True:
            await asyncio.sleep(86400)
