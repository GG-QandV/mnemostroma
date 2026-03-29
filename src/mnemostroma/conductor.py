# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
from pathlib import Path
from typing import Optional

from .config import Config
from .core import SystemContext, ModelRegistry
from .storage.sqlite import init_db, DatabaseManager
from .storage.content_manager import ContentManager
from .storage.log_writer import LogWriter
from .memory.hnsw import init_session_index, init_content_index
from .memory.dissolver import Dissolver
from .memory.consolidation import ConsolidationWorker
# Model loaders now managed by ModelRegistry
from .feedback.implicit import ImplicitFeedbackTracker
from .integration.proxy import ConductorProxy, MemoryBlock

logger = logging.getLogger("mnemostroma.conductor")

class Conductor:
    """System orchestrator for Mnemostroma.
    
    Handles startup, shutdown, piping interactions, and wiring of all components.
    """
    def __init__(self):
        self.ctx: Optional[SystemContext] = None
        self.proxy: Optional[ConductorProxy] = None

    async def start(
        self, 
        config_path: str | Path = "config.json",
        db_path: str | Path = "mnemostroma.db",
        model_dir: str | Path = "models"
    ) -> SystemContext:
        """Initialize the entire system.
        
        Orchestration steps:
        1. Load Config.
        2. Init SQLite and DatabaseManager.
        3. Init HNSW Indices.
        4. Load ONNX Models (Registry).
        5. Setup Content Branch.
        6. Start Workers (Consolidation, Flush).
        
        Returns:
            SystemContext: Fully initialized global context.
        """
        logger.info("Starting Mnemostroma Conductor...")
        
        # 1. Config
        config = Config.load(Path(config_path))
        
        # 2. Storage
        db = await init_db(Path(db_path), config=config)
        db_manager = DatabaseManager(db, config)
        await db_manager.start()
        
        # 3. Memory Indices
        hnsw_session = init_session_index(config)
        # Content HNSW init logic
        hnsw_content = init_content_index(config)
        
        # 4. Models — fully delegated to ModelRegistry's lazy loading (Phase 7 fix)
        model_registry = ModelRegistry(config=config)
        
        # 5. Global Context
        self.ctx = SystemContext(
            config=config,
            db=db,
            hnsw_session=hnsw_session,
            hnsw_content=hnsw_content,
            models=model_registry
        )
        # Wire references
        self.ctx.db_manager = db_manager
        self.ctx.log_writer = log_writer
        self.ctx.content = ContentManager(self.ctx)
        self.ctx.dissolver = Dissolver(self.ctx)
        
        # Wire references
        db_manager.ctx = self.ctx
        
        # B01: Wire ImplicitFeedbackTracker (feedback_loop_v1.5.md § 4)
        self.ctx.feedback_tracker = ImplicitFeedbackTracker(self.ctx)
        
        # Integration Proxy
        self.proxy = ConductorProxy(self.ctx)
        
        # 6. Workers
        await self.ctx.dissolver.start()
        self.ctx.consolidation = ConsolidationWorker(self.ctx)
        await self.ctx.consolidation.start()
        
        # System started

        logger.info("Mnemostroma system bootstrap complete.")
        return self.ctx

    async def stop(self):
        """Shutdown the system and save state."""
        if self.ctx:
            logger.info("Stopping Mnemostroma...")
            if self.ctx.db_manager:
                await self.ctx.db_manager.stop()
            if self.ctx.dissolver:
                await self.ctx.dissolver.stop()
            if self.ctx.consolidation:
                await self.ctx.consolidation.stop()
            if self.ctx.db:
                await self.ctx.db.close()
            logger.info("Mnemostroma shutdown complete.")

    async def inject(self, user_message: str, max_tokens: int = 600, include_tools: bool = True) -> MemoryBlock:
        """Inject memory context for the LLM prompt.
        
        Delegates to the ConductorProxy to generate an XML memory block 
        based on the user's latest message and current active session state.
        """
        if not self.proxy:
            raise RuntimeError("Conductor not started. Call start() first.")
        return await self.proxy.inject(user_message, max_tokens, include_tools)
        
    async def observe(self, session_id: str, text: str):
        """Pass an interaction transcript to the active Observer pipeline."""
        if not self.ctx:
            raise RuntimeError("Conductor not started. Call start() first.")
            
        from .observer.pipeline import observer_pipeline
        # Creates a background task to not block the main agent workflow
        asyncio.create_task(observer_pipeline(text, session_id, self.ctx))
