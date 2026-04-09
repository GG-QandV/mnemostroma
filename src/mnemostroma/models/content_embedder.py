# SPDX-License-Identifier: FSL-1.1-MIT
"""Content embedding model using BGE-M3 (ONNX)."""
import logging
import os
import numpy as np

logger = logging.getLogger(__name__)

class BGEM3Encoder:
    """ONNX wrapper for BGE-M3 INT8 for the Content branch.
    
    Provides highly accurate document-level chunks.
    """
    def __init__(self, model_dir: str):
        self.model_dir = model_dir
        self.session = None
        self.tokenizer = None
        self._loaded = False
        
    def _load(self) -> None:
        if self._loaded:
            return
            
        try:
            # Requires optimum for BGE setup
            from optimum.onnxruntime import ORTModelForCustomTasks
            from transformers import AutoTokenizer
            
            # If not using exact hub names, point to local dir
            if not os.path.exists(self.model_dir):
                raise FileNotFoundError(
                    f"Content embedder model dir not found: {self.model_dir}"
                )
                
            # Ideally load from optimum custom ONNX or fallback to raw implementation
            # Since standard usage assumes local dir with BGE files:
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
            self.session = ORTModelForCustomTasks.from_pretrained(self.model_dir)
            
            self._loaded = True
            logger.info("Successfully loaded BGEM3Encoder ONNX")
        except Exception as e:
            logger.error(f"Failed to load BGEM3 ONNX: {e}")
            raise

    def encode(self, text: str) -> np.ndarray:
        """Encode text into a dense vector via BGE."""
        if not self._loaded:
            self._load()
            
        try:
            inputs = self.tokenizer(text, return_tensors="pt", padding=True, truncation=True, max_length=512)
            # ORT output extraction depends on the specific exported format.
            # Usually the pooled output or mean pooling across CLS token.
            outputs = self.session(**inputs)
            # Placeholder for standard HF outputs
            if hasattr(outputs, "last_hidden_state"):
                vec = outputs.last_hidden_state[:, 0].detach().numpy()[0]
            else:
                # Direct array from generic ORT
                vec = list(outputs.values())[0][0][0]
                
            norm = float(np.linalg.norm(vec))
            if norm == 0:
                norm = 1.0
                
            return (vec / norm).astype(np.float16)
            
        except Exception as e:
            logger.error(f"Content encoding failed: {e}")
            raise
