# SPDX-License-Identifier: FSL-1.1-MIT
"""ONNX-based embedding engine implementation."""
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from . import footprint

logger = logging.getLogger(__name__)

_POOLING_MODES = ("mean", "cls")


class ONNXEmbeddingEngine:
    """Local ONNX embedding engine.
    
    Memory footprint (GTE-multilingual-base INT8):
        ONNX session: ~640 MB (INT8 weights + float32 compute buffers)
        Tokenizer:    ~290 MB (sentencepiece vocab in memory)
        Total:        ~930 MB per unique model
    
    Thread safety:
        tokenizer: safe (Rust impl, releases GIL)
        session.run: safe with controlled thread count
    """
    
    def __init__(
        self,
        model_path: str | Path,
        tokenizer_path: str | Path,
        dim: int = 768,
        max_length: int = 512,
        threads: int = 2,
        intra_threads: int = 2,
        query_prefix: str = "",
        pooling: str = "mean",
        graph_optimization_level: str | None = None,
        disable_prepacking: bool = False,
    ):
        if pooling not in _POOLING_MODES:
            raise ValueError(
                f"Unsupported pooling mode: {pooling!r} (expected one of {_POOLING_MODES})"
            )
        self._pooling = pooling
        self._dim = dim
        self._max_length = max_length
        self._model_path = str(model_path)
        self._query_prefix = query_prefix

        t0 = time.monotonic()

        # ONNX session
        sess_options = ort.SessionOptions()
        sess_options.inter_op_num_threads = threads
        sess_options.intra_op_num_threads = intra_threads
        sess_options.enable_cpu_mem_arena = False
        sess_options.enable_mem_pattern = False
        level_name = graph_optimization_level or "ORT_ENABLE_ALL"
        try:
            sess_options.graph_optimization_level = getattr(ort.GraphOptimizationLevel, level_name)
        except AttributeError:
            raise ValueError(f"Unknown graph_optimization_level: {level_name!r}") from None
        if disable_prepacking:
            sess_options.add_session_config_entry("session.disable_prepacking", "1")
        self._footprint_key = f"engine:{self._model_path}"
        with footprint.measure(self._footprint_key):
            self.session = ort.InferenceSession(self._model_path, sess_options)
        
        t_session = time.monotonic()
        
        # Tokenizer
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        
        t_done = time.monotonic()
        
        # Executor for async
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="onnx-emb")
        
        logger.info(
            "engine.create | model=%s dim=%d max_len=%d pooling=%s opt=%s "
            "| session=%.1fs tokenizer=%.1fs total=%.1fs",
            Path(model_path).parent.name,
            dim,
            max_length,
            self._pooling,
            level_name,
            t_session - t0,
            t_done - t_session,
            t_done - t0,
        )
    
    @property
    def dim(self) -> int:
        return self._dim
    
    def encode(self, text: str, max_length: int | None = None) -> np.ndarray:
        """Encode text → normalized float16 vector (dim,).

        Pooling per model: attention-masked mean (B04 fix) or CLS/first token.
        """
        t0 = time.monotonic()
        
        # 0. Apply model-specific instructions (e.g. "query: ")
        if self._query_prefix:
            text = self._query_prefix + text
            
        length = max_length or self._max_length
        self.tokenizer.enable_truncation(max_length=length)
        encoded = self.tokenizer.encode(text)
        
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        
        feed = {
            "input_ids": input_ids,
            "attention_mask": attention_mask,
        }
        
        # Check if model requires token_type_ids (Xenova-style E5/BERT)
        sess_input_names = [i.name for i in self.session.get_inputs()]
        if "token_type_ids" in sess_input_names:
            feed["token_type_ids"] = np.array([encoded.type_ids], dtype=np.int64)
            
        outputs = self.session.run(None, feed)
        
        token_embeddings = outputs[0]  # (1, seq_len, dim)

        if self._pooling == "cls":
            # CLS / first token — granite-embedding-*-r2 (1_Pooling: pooling_mode_cls_token)
            pooled = token_embeddings[0, 0, :]
        else:
            # Attention-masked mean pooling
            mask_expanded = attention_mask[:, :, np.newaxis].astype(np.float32)
            sum_embeddings = np.sum(token_embeddings * mask_expanded, axis=1)
            sum_mask = np.clip(np.sum(mask_expanded, axis=1), a_min=1e-9, a_max=None)
            pooled = (sum_embeddings / sum_mask)[0]  # (dim,)

        # MRL Truncation if needed
        if len(pooled) > self._dim:
            pooled = pooled[:self._dim]

        # L2 normalize
        norm = np.linalg.norm(pooled)
        if norm > 0:
            pooled = pooled / norm

        result = pooled.astype(np.float16)
        
        logger.debug(
            "encode | tokens=%d dim=%d latency=%.0fms",
            len(encoded.ids),
            self._dim,
            (time.monotonic() - t0) * 1000,
        )
        
        return result
    
    async def aencode(self, text: str, max_length: int | None = None) -> np.ndarray:
        """Non-blocking async encode."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            self.encode,
            text,
            max_length,
        )
    
    def close(self) -> None:
        """Release executor. ONNX session freed by GC."""
        self._executor.shutdown(wait=False)
        self.session = None
        footprint.release(self._footprint_key)
        logger.info("engine.close | model=%s", Path(self._model_path).parent.name)
    
    def __repr__(self) -> str:
        return f"ONNXEmbeddingEngine({Path(self._model_path).parent.name}, dim={self._dim})"
