"""Mnemostroma Core subsystems
Contains bootstrap, lifecycle, and monitoring logic extracted from main.py.
"""
# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, List
import aiosqlite
from ..config import Config
from ..subconscious.anchor_index import AnchorIndex

logger = logging.getLogger(__name__)


@dataclass
class ModelRegistry:
    """Registry for ONNX models with manifest-driven loading.
    
    Embedding models managed via EnginePool — automatic deduplication
    by model path. Same path = same engine = no memory waste.
    Different paths = separate engines = automatic.
    
    Attributes:
        config: System configuration.
        _pool: Embedding engine pool (deduplicates by path).
        _ner: Zero-shot NER model (lazy).
        _reranker: Cross-encoder reranking model (lazy).
    """
    config: Config
    model_dir: Optional[Path] = None
    _pool: Any = field(default=None, repr=False)
    _ner: Any = None
    _reranker: Any = None

    def __post_init__(self):
        from ..models.engine_pool import EnginePool
        self._pool = EnginePool(
            inter_threads=self.config.resources.onnx_inter_threads,
            intra_threads=self.config.resources.onnx_intra_threads,
        )

    def _resolve_model_path(self, path: str) -> str:
        """Resolve model path: if not absolute, resolve relative to ~/.mnemostroma/ or CWD."""
        p = Path(path)
        if p.is_absolute():
            return str(p)
        
        # User-mode: ~/.mnemostroma/<path>
        user_path = Path.home() / ".mnemostroma" / path
        if user_path.exists():
            return str(user_path)
            
        # Dev-mode or already correct: ./<path>
        return str(p)

    @property
    def embedder(self) -> Any:
        """Session embedder — routed through pool."""
        m_def = self.config.manifest.active_models["session_embedder"]
        m_def = m_def.__class__(
            path=self._resolve_model_path(m_def.path),
            query_prefix=m_def.query_prefix,
            tokenizer_path=self._resolve_model_path(m_def.tokenizer_path) if m_def.tokenizer_path else None,
            dim=m_def.dim,
            max_length=m_def.max_length,
            pooling=m_def.pooling
        )
        return self._pool.get(m_def)

    @property
    def content_embedder(self) -> Any:
        """Content embedder — routed through pool.
        
        If manifest points to same model as session_embedder,
        pool returns the same engine instance (zero extra memory).
        """
        m_def = self.config.manifest.active_models["content_embedder"]
        m_def = m_def.__class__(
            path=self._resolve_model_path(m_def.path),
            query_prefix=m_def.query_prefix,
            tokenizer_path=self._resolve_model_path(m_def.tokenizer_path) if m_def.tokenizer_path else None,
            dim=m_def.dim,
            max_length=m_def.max_length,
            pooling=m_def.pooling
        )
        return self._pool.get(m_def)

    @property
    def ner(self) -> Any:
        """Lazy load GLiNER."""
        if self._ner is None:
            from ..models.ner_observer import GLiNERObserver
            m_def = self.config.manifest.active_models["ner"]
            path = self._resolve_model_path(m_def.path)
            tok_path = self._resolve_model_path(m_def.tokenizer_path) if m_def.tokenizer_path else None
            self._ner = GLiNERObserver(path, tok_path)
        return self._ner

    @property
    def reranker(self) -> Any:
        """Lazy load Reranker."""
        if self._reranker is None:
            from ..models.reranker import TinyBERTReranker
            m_def = self.config.manifest.active_models["reranker"]
            path = self._resolve_model_path(m_def.path)
            tok_path = self._resolve_model_path(m_def.tokenizer_path) if m_def.tokenizer_path else None
            self._reranker = TinyBERTReranker(path, tok_path)
        return self._reranker

    def close(self):
        """Release all engine resources."""
        if self._pool:
            self._pool.close_all()
        logging.getLogger(__name__).info("ModelRegistry.close | all engines released")


@dataclass
class SystemContext:
    """Global system context passed to all components.
    
    Attributes:
        config: System configuration.
        ram_index: Current sessions in RAM Hot/Warm layers.
        session_index: MatrixSearch index for session vectors.
        content_index: MatrixSearch index for content vectors.
        db: Active SQLite connection.
        models: Registry for ONNX models.
        metrics: Dictionary for system metrics and telemetry.
        sid_to_id: Mapping from session_id to matrix row label.
        id_to_sid: Mapping from matrix row label to session_id.
    """
    config: Config
    ram_index: Dict[str, Any] = field(default_factory=dict)
    session_index: Optional[Any] = None
    content_index: Optional[Any] = None
    db: Optional[aiosqlite.Connection] = None
    models: Optional[ModelRegistry] = None
    metrics: Dict[str, Any] = field(default_factory=dict)

    id_to_sid: Dict[int, str] = field(default_factory=dict)
    sid_to_id: Dict[str, int] = field(default_factory=dict)

    # Content label mappings for content_index
    id_to_cid: Dict[int, str] = field(default_factory=dict)
    cid_to_id: Dict[str, int] = field(default_factory=dict)

    # Content Management
    content: Optional['ContentManager'] = None

    # Memory Management
    dissolver: Optional['Dissolver'] = None
    consolidation: Optional['ConsolidationWorker'] = None

    # Infrastructure
    persistence: Optional['PersistenceLayer'] = None
    log_writer: Optional['LogWriter'] = None
    session_repo: Optional[Any] = None     # Active SessionPort adapter (legacy/shadow/new)
    precision_repo: Optional[Any] = None   # Active PrecisionPort adapter
    anchor_repo: Optional[Any] = None      # Active AnchorPort adapter

    # v1.1 / v1.3 extensions
    urgency_index: Dict[str, Any] = field(default_factory=dict)
    pending_updates: asyncio.Queue = field(default_factory=asyncio.Queue)
    _next_session_label: int = 0
    _next_content_label: int = 0

    # Index concurrency lock — search+add must be atomic
    index_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Pending emotions awaiting entity binding (Memory Model v2 § 5.2)
    pending_emotions: List[Any] = field(default_factory=list)

    # Anchor vectors for marker() classification — pre-warmed at bootstrap (§ 2.3)
    anchor_vectors: Dict[str, Any] = field(default_factory=dict)

    # Onboarding calibration collector
    calibration: Optional[Any] = None

    # Experience Layer index
    experience_index: Optional[Any] = None

    # Feedback Loop
    feedback_tracker: Optional['ImplicitFeedbackTracker'] = None
    
    # Urgency Pulse cache (session_id -> last known level)
    urgency_level_cache: Dict[str, str] = field(default_factory=dict)

    # Session Closure Trigger cooldown
    closure_cooldown_until: float = 0.0

    # Last user message text (Phase 11.A/G)
    last_message_text: str = ""

    # GAP 2: Session IDs injected into last LLM prompt — consumed by ImplicitFeedbackTracker
    _last_injected_ids: List[str] = field(default_factory=list)

    # Phase 11.A/C: Associative Surfacing + Anchor Guardian queues
    surfaced_queue: List[Any] = field(default_factory=list)
    conflict_warnings: List[Any] = field(default_factory=list)
    recently_warned: Dict[str, float] = field(default_factory=dict)  # anchor_id → timestamp

    # Phase 11.E: Open Loop Detector
    open_loops_queue: List[Any] = field(default_factory=list)
    recently_looped: Dict[str, float] = field(default_factory=dict)  # anchor_id → timestamp

    # Phase 11.D: Precision Guard
    # key: (type, context_tag) → {value, session_id, stored_at}
    precision_ram: Dict[tuple, Dict[str, Any]] = field(default_factory=dict)
    precision_warnings: List[Any] = field(default_factory=list)

    # subconscious anchors
    anchor_index: Optional['AnchorIndex'] = field(default_factory=lambda: AnchorIndex(max_capacity=1000))

    def get_session_label(self, session_id: str) -> int:
        """Get existing or assign new deterministic label for session vector."""
        if session_id in self.sid_to_id:
            return self.sid_to_id[session_id]
        label = self._next_session_label
        self._next_session_label += 1
        return label

    def get_content_label(self, content_id: str) -> int:
        """Get existing or assign new deterministic label for content vector."""
        if content_id in self.cid_to_id:
            return self.cid_to_id[content_id]
        label = self._next_content_label
        self._next_content_label += 1
        return label

    async def sync(self, checkpoint_mode: str = "PASSIVE") -> dict:
        """Force-flush all pending RAM→SQLite writes and WAL checkpoint.

        Use before agent handoff, cloud sync, or graceful shutdown.
        Returns stats dict: {flushed_sessions, wal_pages, checkpoint_mode}.
        """
        from ..tools.bridge import ctx_sync
        return await ctx_sync(self, checkpoint_mode=checkpoint_mode)

    async def load(self, session_id: str):
        """Lazy-load a session from cold SQLite storage into RAM+HNSW.

        Returns SessionBrief if found, None otherwise.
        Idempotent: if already in RAM, returns immediately.
        """
        from ..tools.bridge import ctx_load
        return await ctx_load(session_id, self)

    def __post_init__(self):
        pass
