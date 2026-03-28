# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from pathlib import Path
from typing import Optional, Any

class Embedder:
    """EmbeddingGemma-300M ONNX wrapper for session vectorization.
    
    Uses 512d MRL (Matryoshka Representation Learning) truncation.
    """
    def __init__(self, model_path: str | Path, tokenizer_path: str | Path):
        self.session = ort.InferenceSession(str(model_path))
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._dim = 512

    def encode(self, text: str) -> np.ndarray:
        """Encode text into a 512d vector.
        
        Args:
            text: Input string (brief + tags).
            
        Returns:
            np.ndarray: float16[512] vector.
        """
        encoded = self.tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        
        # Attention mask for models that require it
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
        
        inputs = {
            "input_ids": input_ids,
            "attention_mask": attention_mask
        }
        
        outputs = self.session.run(None, inputs)
        # Assuming output is [batch, tokens, hidden_dim] or [batch, hidden_dim]
        # For EmbeddingGemma, we typically take the last token or use a specific pooling
        # Most embedding models return [batch, hidden_dim] after pooling
        vector = outputs[0][0]
        
        # MRL Truncation to 512d
        if len(vector) > self._dim:
            vector = vector[:self._dim]
            
        # Normalize for cosine similarity
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm
            
        return vector.astype(np.float16)

def load_embedder(config: Any, model_dir: Path) -> Embedder:
    """Helper to load embedder from config."""
    model_name = config.models.embedding_session
    path = model_dir / model_name
    return Embedder(
        model_path=path / "model.onnx",
        tokenizer_path=path / "tokenizer.json"
    )
