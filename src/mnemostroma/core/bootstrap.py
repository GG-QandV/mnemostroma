# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from pathlib import Path

from mnemostroma.conductor import Conductor
from mnemostroma.core.lifecycle import register_signal_handlers

logger = logging.getLogger(__name__)

async def bootstrap(
    config_path: str | Path,
    db_path: str | Path,
    model_dir: str | Path
) -> Conductor:
    """Bootstrap the daemon, initialize layers and spawn background workers."""
    conductor = Conductor()
    
    logger.info("Initializing Mnemostroma Daemon...")
    await conductor.start(
        config_path=config_path,
        db_path=db_path,
        model_dir=model_dir,
    )
    
    register_signal_handlers(conductor)

    from mnemostroma.core.monitoring import run_background_workers
    await run_background_workers(conductor)

    return conductor
