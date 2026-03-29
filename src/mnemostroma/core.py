# SPDX-License-Identifier: FSL-1.1-MIT
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, List
import aiosqlite
import hnswlib
from .config import Config

@dataclass
class ModelRegistry:
    """Registry for ONNX models with manifest-driven loading and shared sessions.
    
    Attributes:
        config: System configuration.
        _shared_session: Shared ONNX session for models using the same file.
        _embedder: Session vectorization model.
        _ner: Zero-shot NER model.
        _content_embedder: Content vectorization model.
        _reranker: Cross-encoder reranking model.
    """
    config: Config
    _shared_session: Any = None
    _embedder: Any = None
    _ner: Any = None
    _content_embedder: Any = None
    _reranker: Any = None

    def _get_model_path(self, name: str) -> str:
        """Resolve model path from manifest."""
        if not self.config.manifest or name not in self.config.manifest.active_models:
            raise ValueError(f"Model '{name}' not found in manifest")
        return self.config.manifest.active_models[name].path

    def _get_shared_session(self, model_path: str):
        """Load or return shared ONNX session with memory arena hack."""
        if self._shared_session is None:
            import onnxruntime as ort
            sess_options = ort.SessionOptions()
            sess_options.enable_cpu_mem_arena = False
            sess_options.enable_mem_pattern = False
            self._shared_session = ort.InferenceSession(model_path, sess_options)
        return self._shared_session

    @property
    def embedder(self) -> Any:
        """Lazy load shared embedder."""
        if self._embedder is None:
            from .observer.embedder import Embedder
            m_def = self.config.manifest.active_models["session_embedder"]
            session = self._get_shared_session(m_def.path)
            self._embedder = Embedder(session, m_def.tokenizer_path, dim=m_def.dim, max_length=m_def.max_length)
        return self._embedder

    @property
    def ner(self) -> Any:
        """Lazy load GLiNER."""
        if self._ner is None:
            from .models.ner_observer import GLiNERObserver
            path = self._get_model_path("ner")
            self._ner = GLiNERObserver(path)
        return self._ner

    @property
    def content_embedder(self) -> Any:
        """Lazy load shared content embedder."""
        if self._content_embedder is None:
            from .observer.embedder import Embedder
            m_def = self.config.manifest.active_models["content_embedder"]
            session = self._get_shared_session(m_def.path)
            self._content_embedder = Embedder(session, m_def.tokenizer_path, dim=m_def.dim, max_length=m_def.max_length)
        return self._content_embedder

    @property
    def reranker(self) -> Any:
        """Lazy load Reranker."""
        if self._reranker is None:
            from .models.reranker import TinyBERTReranker
            path = self._get_model_path("reranker")
            self._reranker = TinyBERTReranker(path)
        return self._reranker

@dataclass
class SystemContext:
    """Global system context passed to all components.
    
    Attributes:
        config: System configuration.
        ram_index: Current sessions in RAM Hot/Warm layers.
        hnsw_session: HNSWlib index for session vectors.
        hnsw_content: HNSWlib index for content vectors.
        db: Active SQLite connection.
        models: Registry for ONNX models.
        metrics: Dictionary for system metrics and telemetry.
        sid_to_id: Mapping from session_id to HNSW integer label.
        id_to_sid: Mapping from HNSW integer label to session_id.
    """
    config: Config
    ram_index: Dict[str, Any] = field(default_factory=dict)
    hnsw_session: Optional[hnswlib.Index] = None
    hnsw_content: Optional[hnswlib.Index] = None
    db: Optional[aiosqlite.Connection] = None
    models: Optional[ModelRegistry] = None
    metrics: Dict[str, Any] = field(default_factory=dict)
    
    id_to_sid: Dict[int, str] = field(default_factory=dict)
    sid_to_id: Dict[str, int] = field(default_factory=dict)
    
    # Content Management
    content: Optional['ContentManager'] = None 
    
    # Memory Management
    dissolver: Optional['Dissolver'] = None
    consolidation: Optional['ConsolidationWorker'] = None
    
    # Infrastructure
    db_manager: Optional['DatabaseManager'] = None
    log_writer: Optional['LogWriter'] = None
    
    # v1.1 / v1.3 extensions
    urgency_index: Dict[str, Any] = field(default_factory=dict)  # sid -> UrgencyItem
    pending_updates: asyncio.Queue = field(default_factory=asyncio.Queue)

    # Feedback Loop
    feedback_tracker: Optional['ImplicitFeedbackTracker'] = None

    def get_hnsw_label(self, session_id: str) -> int:
        """Centralized HNSW label generation (31-bit positive int)."""
        return hash(session_id) & 0x7FFFFFFF

    def __post_init__(self):
        """Perform additional setup if needed."""
        pass
