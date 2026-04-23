# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
import os as _os
import threading
import time
import time as _time
import numpy as np
import sys
from pathlib import Path
from typing import Optional, Any

_SESS_DIAG_KEY_ = ""  # watermark anchor — injected per-tester by issue_build.py

_HEARTBEAT_FILE     = Path.home() / ".mnemostroma" / "daemon.heartbeat"
_HEARTBEAT_INTERVAL = 1.0   # seconds
_LOOP_DRIFT_LIMIT   = 5.0   # seconds — loop_monitor threshold

from .config import Config
from .core import SystemContext, ModelRegistry
from .storage.sqlite import init_db, DatabaseManager, check_anchor_schema
from .storage.persistence import PersistenceLayer
from .storage.content_manager import ContentManager
from .memory.hnsw import init_session_index, init_content_index
from .memory.dissolver import Dissolver
from .memory.consolidation import ConsolidationWorker
from .memory.daemon_metrics import PulseWriter, StatusWriter
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
        self._last_observe_at: float = 0.0
        self._dreamer_task: Optional[asyncio.Task] = None
        self._pulse_writer: Optional[PulseWriter] = None
        self._status_writer: Optional[StatusWriter] = None
        self._backup_worker: Optional[Any] = None
        self._stopping: bool = False

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
        self._start_heartbeat_thread()
        
        # 1. Config
        config = Config.load(Path(config_path))
        
        # 2. Storage
        db = await init_db(Path(db_path), config=config)
        db_manager = DatabaseManager(db, config)
        await db_manager.start()
        
        # B0.5: Dimension Migration (Wipe stale embeddings if 768 -> 384 mismatch)
        await db_manager.check_embedding_dim(config.search.embedding_dim)
        # B0.6: Experience schema migration (adds emotion columns if missing — v1.4)
        await db_manager.check_experience_schema()
        # B0.7: Anchor t_rel migration (adds t_rel column if missing — v1.6 §5.1)
        await check_anchor_schema(db)
        
        # 2.5 Logging (v1.0 spec) — skipped when logging.enabled: false
        logs_path = config.logging.db_path
        log_writer = None
        if config.logging.enabled:
            log_writer = LogWriter(logs_path)
            await log_writer.start()
        
        # 3. Memory Indices (matrix cosine search — ADR-002)
        session_index = init_session_index(config)
        content_index = init_content_index(config)

        # 4. Models — fully delegated to ModelRegistry's lazy loading (Phase 7 fix)
        model_registry = ModelRegistry(config=config, model_dir=Path(model_dir))

        # 5. Global Context
        self.ctx = SystemContext(
            config=config,
            db=db,
            session_index=session_index,
            content_index=content_index,
            models=model_registry
        )
        # Wire references
        persistence = PersistenceLayer(db_manager)
        self.ctx.persistence = persistence
        self.ctx.log_writer = log_writer
        self.ctx.content = ContentManager(self.ctx)
        self.ctx.dissolver = Dissolver(self.ctx)

        # Phase 2: SessionRepo Wiring
        repo_mode = config.storage.session_repo
        if repo_mode in ("new", "shadow"):
            from .adapters.sqlite.session_repo import SessionRepo
            from .adapters.sqlite.precision_repo import PrecisionRepo
            from .adapters.sqlite.anchor_repo import AnchorRepo
            self.ctx.session_repo = SessionRepo(db_manager)
            self.ctx.precision_repo = PrecisionRepo(db_manager)
            self.ctx.anchor_repo = AnchorRepo(db_manager)
            logger.info("SessionRepo mode: ACTIVE (adapters-only)")
        else:
            self.ctx.session_repo = None # Legacy/PersistenceLayer only
            self.ctx.precision_repo = None
            self.ctx.anchor_repo = None
            logger.info("SessionRepo mode: LEGACY (PersistenceLayer direct)")

        # Provide ctx to db_manager for internal instrumentation access
        persistence.wire_ctx(self.ctx)
        await persistence.start()
        
        # ADR-002: validate pipeline_width does not exceed available ONNX threads
        pw = config.search.pipeline_width
        oit = config.resources.onnx_inter_threads
        if pw > oit:
            logger.warning(
                f"config: pipeline_width={pw} > onnx_inter_threads={oit} — "
                "parallel ONNX calls will contend for threads; reduce pipeline_width or increase onnx_inter_threads"
            )

        # B01: Cold Bootstrap Hydration (SQLite -> RAM Index & HNSW)
        # Must happen BEFORE starting workers to avoid race conditions
        await self._hydrate_indices(self.ctx)

        # B01.5: Pre-warm anchor vectors (marker § 2.3) — eliminates first-request latency spike
        await self._warmup_anchor_vectors(self.ctx)

        # B01.6: Preload precision_ram from precision_log (Phase 11.D)
        if config.precision_guard.enabled:
            try:
                async with db.execute(
                    """SELECT type, value, context_tag, created_at
                       FROM precision_log
                       ORDER BY created_at DESC LIMIT 500"""
                ) as cur:
                    rows = await cur.fetchall()
                for ptype, value, ctx_tag, created_at in rows:
                    if ptype in ("link", "version", "number"):
                        key = (ptype, ctx_tag or "unknown")
                        if key not in self.ctx.precision_ram:  # newest wins (DESC order)
                            self.ctx.precision_ram[key] = {
                                "value": value,
                                "stored_at": created_at,
                            }
                logger.info(f"Precision RAM preloaded: {len(self.ctx.precision_ram)} entries")
            except Exception as e:
                logger.warning(f"Precision RAM preload failed: {e}")

        # B02: Wire ImplicitFeedbackTracker (feedback_loop_v1.5.md § 4)
        self.ctx.feedback_tracker = ImplicitFeedbackTracker(self.ctx)

        # Onboarding: passive calibration collector (no-op if already calibrated)
        if config.calibration.enabled and not config.calibration.calibration_complete:
            from .observer.calibration import CalibrationCollector
            self.ctx.calibration = CalibrationCollector(self.ctx, config_path=str(config_path))

        # Experience Layer
        if config.experience.layer_enabled:
            from .memory.experience import ExperienceIndex
            exp_index = ExperienceIndex(
                signal_threshold=config.experience.intuition_fire_threshold,
                maturity_apprentice=config.experience.maturity_apprentice,
                maturity_practitioner=config.experience.maturity_practitioner,
                maturity_expert=config.experience.maturity_expert,
                maturity_master=config.experience.maturity_master,
            )
            rows = await persistence.load_experience()
            exp_index.load(rows)
            self.ctx.experience_index = exp_index
            logger.info(f"Experience Layer loaded: {len(rows)} clusters")
        
        # Integration Proxy
        self.proxy = ConductorProxy(self.ctx)
        
        # 6. Workers
        await self.ctx.dissolver.start()
        self.ctx.consolidation = ConsolidationWorker(self.ctx)
        await self.ctx.consolidation.start()

        # 6.6 Daemon metrics writers (pulse.json + status.json for external monitoring)
        self._pulse_writer = PulseWriter(self.ctx)
        self._status_writer = StatusWriter(self.ctx)
        self._backup_worker = None
        if hasattr(self.ctx.config, "storage"):
            from .core.backup import BackupWorker
            self._backup_worker = BackupWorker(self.ctx)
            # Store db_path for BackupWorker
            self.ctx.db_path = str(db_path)

        await self._pulse_writer.start()
        await self._status_writer.start()
        if self._backup_worker:
            await self._backup_worker.start()

        # 6.5 Dreamer (Stage D — idle-triggered anchor reassessment)
        dreamer_cfg = getattr(config, 'dreamer', None)
        if dreamer_cfg and dreamer_cfg.enabled:
            from .subconscious.dreamer import Dreamer
            dreamer = Dreamer(conductor=self, ctx=self.ctx)
            await dreamer.start()
            self._dreamer_task = dreamer
        
        # Initial Bootstrap Log

        # B03: Health Check Log (v1.0 spec — Point #17)
        try:
            import psutil, os
            _rss = psutil.Process(os.getpid()).memory_info().rss
            _ram_mb = round(_rss / 1024 / 1024, 2)
        except Exception:
            _ram_mb = -1.0
        
        # Heartbeat + loop monitor + outbox worker
        self._stopping = False
        asyncio.create_task(self._loop_monitor(),  name="loop_monitor")
        asyncio.create_task(self._outbox_worker(), name="outbox_worker")
        asyncio.create_task(self._cleanup_loop(),  name="outbox_cleanup")

        # UI Auto-start
        if config.ui.tray_enabled:
            self._start_tray_detached()

        logger.info("Mnemostroma system bootstrap complete.")
        return self.ctx

    async def _hydrate_indices(self, ctx: SystemContext):
        """Reconstruct matrix search index and RAM maps from SQLite (Cold Bootstrap)."""
        logger.info("Starting index hydration from SQLite...")

        # 1. Hydrate Metadata (ram_index)
        briefs = await ctx.persistence.get_all_session_briefs()
        for sb in briefs:
            ctx.ram_index[sb.session_id] = sb

        # 2. Hydrate session matrix
        model_def = ctx.config.manifest.active_models.get("session_embedder") if ctx.config.manifest else None
        expected_dim = model_def.dim if model_def and model_def.dim else ctx.config.search.embedding_dim

        embeddings = await ctx.persistence.get_all_embeddings(expected_dim)

        if not embeddings:
            logger.info("Hydration: No embeddings found in DB.")
            return

        vectors = []
        labels = []
        for sid, vec in embeddings:
            label = ctx.get_session_label(sid)
            ctx.id_to_sid[label] = sid
            ctx.sid_to_id[sid] = label
            vectors.append(vec.astype('float32'))
            labels.append(label)

        ctx.session_index.add_items(vectors, labels)
        ctx._next_session_label = len(embeddings)

        logger.info(f"Hydration complete: {len(embeddings)} sessions restored. "
                    f"next_label={ctx._next_session_label}")

        # 3. Hydrate content matrix
        content_model_def = ctx.config.manifest.active_models.get("content_embedder") if ctx.config.manifest else None
        content_dim = content_model_def.dim if content_model_def and content_model_def.dim else ctx.config.search.embedding_dim

        content_embeddings = await ctx.persistence.get_all_content_embeddings(content_dim)

        if content_embeddings:
            c_vectors = []
            c_labels = []
            for content_id, version, vec in content_embeddings:
                key = f"{content_id}_{version}"
                label = ctx.get_content_label(key)
                ctx.id_to_cid[label] = key
                ctx.cid_to_id[key] = label
                c_vectors.append(vec.astype('float32'))
                c_labels.append(label)

            ctx.content_index.add_items(c_vectors, c_labels)
            logger.info(f"Content hydration: {len(content_embeddings)} vectors restored.")
        else:
            logger.info("Content hydration: no content embeddings found.")

        # 4. Hydrate Anchors (Subconscious Layer Stage A)
        if ctx.persistence:
            anchors = await ctx.persistence.load_anchors(limit=1000)
            for a in anchors:
                ctx.anchor_index.put(a)
            logger.info(f"Anchor hydration: {len(anchors)} anchors restored to subconscious RAM index.")


    async def _warmup_anchor_vectors(self, ctx) -> None:
        """Pre-encode anchor texts into ctx.anchor_vectors at bootstrap.

        Eliminates first-request latency spike and race condition under
        pipeline_width=4. No-op if embedder is unavailable (tests / offline).
        """
        from .observer.marker import ANCHORS
        embedder = ctx.models.embedder if ctx.models else None
        if embedder is None:
            logger.info("Anchor warmup skipped: no embedder available.")
            return

        import numpy as np
        vectors: dict = {}
        for label, anchor_text in ANCHORS.items():
            try:
                vec = await embedder.aencode(anchor_text)
                v = np.array(vec, dtype=np.float32).flatten()
                norm = np.linalg.norm(v)
                if norm > 1e-9:
                    v = v / norm
                vectors[label] = v
            except Exception as e:
                logger.warning(f"Anchor warmup: failed to encode '{label}': {e}")

        ctx.anchor_vectors = vectors
        logger.info(f"Anchor warmup complete: {len(vectors)}/{len(ANCHORS)} vectors ready.")

    async def stop(self):
        """Shutdown the system and save state."""
        self._stopping = True
        # F-1: conductor.shutdown telemetry — fired before teardown sequence
        import time as _t_stop
        try:
            import psutil as _ps, os as _ps_os
            _ram_mb_stop = round(
                _ps.Process(_ps_os.getpid()).memory_info().rss / 1024 / 1024, 2
            )
        except Exception:
            _ram_mb_stop = -1.0
        if self.ctx and self.ctx.log_writer:
            await _le_stop(self.ctx, "conductor.shutdown", "stop", {
                "reason": "api_call",
                "ram_mb": _ram_mb_stop,
                "sessions_in_ram": len(self.ctx.ram_index),
                "flush_queue_depth": self.ctx.log_writer.queue.qsize(),
                "uptime_seconds": int(_t_stop.time() - getattr(self.ctx, "_started_at", _t_stop.time())),
            }, level="WARNING")
            await asyncio.sleep(0.1)
        await asyncio.sleep(1)  # last pass for outbox_worker

        if self.ctx:
            logger.info("Stopping Mnemostroma...")
            if self._pulse_writer:
                await self._pulse_writer.stop()
            if self._status_writer:
                await self._status_writer.stop()
            if self._backup_worker:
                await self._backup_worker.stop()
            if self.ctx.persistence:
                await self.ctx.persistence.stop()
            if self.ctx.dissolver:
                await self.ctx.dissolver.stop()
            if self.ctx.consolidation:
                await self.ctx.consolidation.stop()
            if self._dreamer_task:
                await self._dreamer_task.stop()
            if self.ctx.log_writer:
                await self.ctx.log_writer.stop()
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
        
    async def observe(self, session_id: str, text: str) -> asyncio.Task:
        """Pass an agent output transcript to the active Observer pipeline."""
        if not self.ctx:
            raise RuntimeError("Conductor not started. Call start() first.")

        import time as _time
        self._last_observe_at = _time.time()

        from .observer.pipeline import observer_pipeline
        task = asyncio.create_task(observer_pipeline(text, session_id, self.ctx))
        task.add_done_callback(self._handle_task_exception)
        return task

    async def observe_user(self, text: str) -> None:
        """Store the user's last message for same-turn signal detection.

        Called by IPC/MCP adapter when a user message arrives, before the agent
        generates a response. Enables Closure Trigger (11.G) and Layer 1 Surfacing (11.A).

        Args:
            text: Raw user message text.
        """
        if not self.ctx:
            return
        self.ctx.last_message_text = text

    def is_idle(self) -> bool:
        """True if no observe() call for longer than dreamer.idle_threshold_min."""
        if not self.ctx or self._last_observe_at == 0.0:
            return False
        import time as _time
        cfg = getattr(self.ctx.config, 'dreamer', None)
        threshold_sec = (cfg.idle_threshold_min if cfg else 5) * 60
        return (_time.time() - self._last_observe_at) >= threshold_sec

    def _handle_task_exception(self, task: asyncio.Task):
        """Unified callback to catch background observer failures."""
        if task.cancelled():
            return
        try:
            exc = task.exception()
            if exc:
                logger.error(f"Observer task failed: {exc}", exc_info=exc)
        except asyncio.InvalidStateError:
            pass

    # ── Heartbeat thread ──────────────────────────────────────────────
    def _start_heartbeat_thread(self) -> None:
        def _beat():
            while not self._stopping:
                try:
                    _HEARTBEAT_FILE.write_text(str(int(_time.time())))
                except Exception:
                    pass
                _time.sleep(_HEARTBEAT_INTERVAL)
        t = threading.Thread(target=_beat, daemon=True, name="mnemostroma-hb")
        t.start()

    # ── Loop monitor ──────────────────────────────────────────────────
    async def _loop_monitor(self) -> None:
        while True:
            t0 = _time.monotonic()
            await asyncio.sleep(3)
            drift = _time.monotonic() - t0 - 3
            if drift > _LOOP_DRIFT_LIMIT:
                logger.critical(f"Event loop drift {drift:.1f}s -> SIGKILL")
                _os._exit(1)

    # ── Outbox worker ─────────────────────────────────────────────────
    async def _outbox_worker(self) -> None:
        MAX_RETRY = 3
        while True:
            try:
                rows = await self.ctx.persistence.outbox_pending(limit=20)
                for row in rows:
                    if row["retry"] >= MAX_RETRY:
                        await self.ctx.persistence.outbox_mark(row["id"], "failed")
                        continue
                    try:
                        await self.observe(row["session_id"], row["text"])
                        await self.ctx.persistence.outbox_mark(row["id"], "done")
                    except Exception as e:
                        logger.warning(f"Outbox retry {row['id']}: {e}")
                        await self.ctx.persistence.outbox_mark(
                            row["id"], "pending", retry=row["retry"] + 1
                        )
            except Exception as e:
                logger.error(f"Outbox worker error: {e}")
            await asyncio.sleep(0.5)

    # ── Cleanup loop ──────────────────────────────────────────────────
    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(86400)
            n = await self.ctx.persistence.outbox_cleanup(older_than_days=7)
            if n:
                logger.info(f"Outbox cleanup: {n} records removed")

    # ── dispatch() ────────────────────────────────────────────────────
    async def dispatch(self, name: str, args: dict):
        ctx = self.ctx
        if ctx is None:
            raise RuntimeError("Conductor not started")

        # READ
        if name == "ctx_semantic":
            from mnemostroma.tools.read import ctx_semantic
            return await ctx_semantic(query=args["query"], ctx=ctx,
                                      top_n=args.get("top_n", 5))
        if name == "ctx_get":
            from mnemostroma.tools.read import ctx_get
            return await ctx_get(args["session_id"], ctx)
        if name == "ctx_active":
            from mnemostroma.tools.read import ctx_active
            return await ctx_active(ctx)
        if name == "ctx_search":
            from mnemostroma.tools.read import ctx_search
            return await ctx_search(tags=args["tags"], ctx=ctx,
                                    importance=args.get("importance"),
                                    age=args.get("age"),
                                    limit=args.get("limit", 10))
        if name == "ctx_full":
            from mnemostroma.tools.read import ctx_full
            return await ctx_full(args["session_id"], ctx)
        if name == "ctx_anchors":
            from mnemostroma.tools.read import ctx_anchors
            return await ctx_anchors(ctx=ctx,
                                     anchor_type=args.get("anchor_type"),
                                     session_id=args.get("session_id"),
                                     limit=args.get("limit", 20))
        if name == "ctx_precision":
            from mnemostroma.tools.read import ctx_precision
            return await ctx_precision(ctx=ctx,
                                       precision_type=args.get("precision_type"),
                                       importance=args.get("importance"),
                                       limit=args.get("limit", 20))
        if name == "ctx_recent":
            from mnemostroma.tools.read import ctx_recent
            return await ctx_recent(ctx=ctx, days=args.get("days", 7.0),
                                    by=args.get("by", "created"),
                                    limit=args.get("limit", 20))
        if name == "ctx_urgent":
            from mnemostroma.tools.write import ctx_urgent
            return await ctx_urgent(ctx, hours_ahead=args.get("hours_ahead", 72.0))

        # WRITE
        if name == "ctx_expire":
            from mnemostroma.tools.write import ctx_expire
            await ctx_expire(args["session_id"], ctx)
            return {"expired": True}
        if name == "save_content":
            from mnemostroma.tools.write import save_content
            return await save_content(
                content_id   = args["content_id"],
                text         = args["text"],
                ctx          = ctx,
                content_type = args.get("content_type"),
                session_id   = args.get("session_id"),
                tags         = args.get("tags"),
                why_changed  = args.get("why_changed"),
            )
        if name == "observe":
            await self.observe(args["session_id"], args["text"])
            return {"ok": True}
        if name == "observe_user":
            await self.observe_user(args["text"])
            return {"ok": True}

        # PROXY ROUTES
        if name == "outbox_put":
            row_id = await ctx.persistence.outbox_put(
                args["session_id"], args["text"]
            )
            return {"queued": True, "id": row_id}
        if name == "inject":
            from mnemostroma.integration.proxy import ConductorProxy
            block = await ConductorProxy(ctx).inject(
                user_message=args.get("user_message", ""),
            )
            return block.context

        # CONTENT
        if name == "content_search":
            from mnemostroma.tools.content import content_search
            return await content_search(query=args["query"], ctx=ctx,
                                        project_id=args.get("project_id"),
                                        status=args.get("status", "active"),
                                        top_k=args.get("topk", 5))
        if name == "content_get":
            from mnemostroma.tools.content import content_get
            return await content_get(args["content_id"], ctx,
                                     version=args.get("version"))
        if name == "content_raw":
            from mnemostroma.tools.content import content_raw
            return await content_raw(args["content_id"], ctx,
                                     version=args.get("version"))
        if name == "content_history":
            from mnemostroma.tools.content import content_history
            return await content_history(args["content_id"], ctx)

        # ADMIN
        if name == "ctx_load":
            from mnemostroma.tools.admin import ctx_load
            return await ctx_load(args["session_id"], ctx)
        if name == "ctx_bridge":
            from mnemostroma.tools.admin import ctx_bridge
            return await ctx_bridge(ctx)

        raise ValueError(f"Unknown tool: {name!r}")

    def _start_tray_detached(self) -> None:
        """Manage the tray icon via systemd user service."""
        import subprocess
        async def _delayed_start():
            await asyncio.sleep(5)
            try:
                logger.info("Ensuring Mnemostroma Tray UI is running via systemd...")
                subprocess.Popen(
                    ["systemctl", "--user", "start", "mnemostroma-ui"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            except Exception as e:
                logger.warning(f"Failed to trigger tray service: {e}")

        asyncio.create_task(_delayed_start())
