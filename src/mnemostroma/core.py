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
    """Registry for ONNX models with lazy loading.
    
    Attributes:
        config: System configuration.
        _embedder: Session vectorization model (EmbeddingGemma).
        _ner: Zero-shot NER model (GLiNER).
        _content_embedder: Content vectorization model (BGE-M3).
        _reranker: Cross-encoder reranking model (TinyBERT).
    """
    config: Config
    _embedder: Any = None
    _ner: Any = None
    _content_embedder: Any = None
    _reranker: Any = None

    def __post_init__(self):
        """Ensure models directory exists."""
        from pathlib import Path
        model_root = Path.home() / ".mnemostroma" / "models"
        model_root.mkdir(parents=True, exist_ok=True)

    @property
    def embedder(self) -> Any:
        """Lazy load EmbeddingGemma-300M."""
        if self._embedder is None:
            import os
            from pathlib import Path
            from .models.session_embedder import EmbeddingGemmaEncoder
            model_dir = str(Path.home() / ".mnemostroma" / "models" / "embeddinggemma-300m")
            self._embedder = EmbeddingGemmaEncoder(model_dir)
        return self._embedder

    @property
    def ner(self) -> Any:
        """Lazy load GLiNER-small."""
        if self._ner is None:
            import os
            from pathlib import Path
            from .models.ner_observer import GLiNERObserver
            model_dir = str(Path.home() / ".mnemostroma" / "models" / "gliner-small-v2.1")
            self._ner = GLiNERObserver(model_dir)
        return self._ner

    @property
    def content_embedder(self) -> Any:
        """Lazy load BGE-M3."""
        if self._content_embedder is None:
            import os
            from pathlib import Path
            from .models.content_embedder import BGEM3Encoder
            model_dir = str(Path.home() / ".mnemostroma" / "models" / "bge-m3-int8")
            self._content_embedder = BGEM3Encoder(model_dir)
        return self._content_embedder

    @property
    def reranker(self) -> Any:
        """Lazy load TinyBERT."""
        if self._reranker is None:
            import os
            from pathlib import Path
            from .models.reranker import TinyBERTReranker
            model_dir = str(Path.home() / ".mnemostroma" / "models" / "tinybert-l2-v2")
            self._reranker = TinyBERTReranker(model_dir)
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
