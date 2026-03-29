# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from pathlib import Path
from typing import Optional, Any

class Embedder:
    """ONNX wrapper for vectorization (e.g. GTE-multilingual-base).
    
    Supports shared sessions and configurable truncation.
    """
    def __init__(
        self, 
        session: ort.InferenceSession, 
        tokenizer_path: str | Path, 
        dim: int = 768, 
        max_length: int = 512
    ):
        self.session = session
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._dim = dim
        self._max_length = max_length

    def encode(self, text: str) -> np.ndarray:
        """Encode text into a vector.
        
        Args:
            text: Input string.
            
        Returns:
            np.ndarray: float16 vector of dimension self._dim.
        """
        self.tokenizer.enable_truncation(max_length=self._max_length)
        encoded = self.tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        
        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask
        }
        
        outputs = self.session.run(None, inputs)
        vector = outputs[0][0]
        
        # MRL Truncation / Fixed dimension
        if len(vector) > self._dim:
            vector = vector[:self._dim]
            
        # Normalize for cosine similarity
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
            
        return vector.astype(np.float16)
