# SPDX-License-Identifier: FSL-1.1-MIT
"""Engine pool — deduplicates embedding engines by model path."""
import logging
from typing import Any

from .onnx_engine import ONNXEmbeddingEngine
from .protocol import EmbeddingEngine

logger = logging.getLogger(__name__)


class EnginePool:
    """Manages embedding engine instances with automatic deduplication.

    Two manifest entries pointing to the same model file
    → one engine instance → one memory footprint.
    
    Two manifest entries pointing to different model files
    → two engine instances → automatic, no code changes.
    """
    
    def __init__(self, inter_threads: int = 2, intra_threads: int = 2):
        self._engines: dict[str, EmbeddingEngine] = {}
        self._inter_threads = inter_threads
        self._intra_threads = intra_threads
    
    def get(self, model_def: Any) -> EmbeddingEngine:
        """Get or create engine for model definition.
        
        Deduplication key: (model_path, tokenizer_path)
        """
        key = self._make_key(model_def)
        
        if key in self._engines:
            logger.debug(
                "pool.hit | key=%s engines_total=%d (reusing existing)",
                self._short_key(key),
                len(self._engines),
            )
            return self._engines[key]
        
        logger.info(
            "pool.miss | key=%s → creating new engine",
            self._short_key(key),
        )
        
        engine = ONNXEmbeddingEngine(
            model_path=model_def.path,
            tokenizer_path=model_def.tokenizer_path,
            dim=model_def.dim,
            max_length=getattr(model_def, "max_length", 512) or 512,
            query_prefix=getattr(model_def, "query_prefix", "") or "",
            pooling=getattr(model_def, "pooling", None) or "mean",
            graph_optimization_level=getattr(model_def, "graph_optimization_level", None),
            disable_prepacking=bool(getattr(model_def, "disable_prepacking", False)),
            threads=self._inter_threads,
            intra_threads=self._intra_threads,
        )
        
        self._engines[key] = engine
        
        logger.info(
            "pool.status | engines_total=%d keys=%s",
            len(self._engines),
            [self._short_key(k) for k in self._engines],
        )
        
        return engine
    
    def close_all(self) -> None:
        """Close all engines and clear pool."""
        count = len(self._engines)
        for engine in self._engines.values():
            engine.close()
        self._engines.clear()
        logger.info("pool.close_all | closed %d engines", count)
    
    @property
    def engine_count(self) -> int:
        return len(self._engines)
    
    @property
    def keys(self) -> list:
        return [self._short_key(k) for k in self._engines]
    
    @staticmethod
    def _make_key(model_def: Any) -> str:
        """Deduplication key.

        Pooling and query prefix are part of the identity: the same file used with
        two different pooling modes is two different engines, and sharing one would
        silently run the second role in the first role's mode.
        """
        pooling = getattr(model_def, "pooling", None) or "mean"
        prefix = getattr(model_def, "query_prefix", None) or ""
        return f"{model_def.path}::{model_def.tokenizer_path}::{pooling}::{prefix}"

    @staticmethod
    def _short_key(key: str) -> str:
        """Shorten for readable logs."""
        parts = key.split("::")
        from pathlib import Path
        if len(parts) >= 2:
            short = f"{Path(parts[0]).name}+{Path(parts[1]).name}"
            if len(parts) >= 3 and parts[2]:
                short += f"/{parts[2]}"
            return short
        return key
