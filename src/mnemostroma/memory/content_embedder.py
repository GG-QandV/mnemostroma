# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from pathlib import Path
from typing import List, Any, Optional

class ContentEmbedder:
    """BGE-M3 (dense-only) ONNX wrapper for content vectorization.
    
    Handles multi-chunk vectorization and weighted mean pooling.
    """
    def __init__(self, model_path: str | Path, tokenizer_path: str | Path):
        self.session = ort.InferenceSession(str(model_path))
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._dim = 512

    def encode_chunks(self, chunks: List[str]) -> np.ndarray:
        """Encode multiple chunks and pool them into a single vector.
        
        Formula: vec_block = mean([v1*1.0, v2*0.8, v3*0.6, ...])
        
        Args:
            chunks: List of text chunks (max 512 tokens each).
            
        Returns:
            np.ndarray: float16[512] aggregated vector.
        """
        vectors = []
        for chunk in chunks:
            encoded = self.tokenizer.encode(chunk)
            input_ids = np.array([encoded.ids], dtype=np.int64)
            attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
            
            inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask
            }
            # BGE-M3 usually returns [batch, tokens, hidden_dim]
            # We take CLS token [0,0] or mean pool
            outputs = self.session.run(None, inputs)
            vec = outputs[0][0] # Simplified logic for INT8 ONNX
            
            # Truncate to 512
            if len(vec) > self._dim:
                vec = vec[:self._dim]
            
            # Normalize
            norm = np.linalg.norm(vec)
            if norm > 0:
                vec = vec / norm
            vectors.append(vec)

        if not vectors:
            return np.zeros(self._dim, dtype=np.float16)

        # Weighted pooling: first chunk has 1.0 weight, others decay
        weighted_vecs = []
        for i, v in enumerate(vectors):
            weight = max(0.2, 1.0 - (i * 0.2))
            weighted_vecs.append(v * weight)
            
        final_vec = np.mean(weighted_vecs, axis=0)
        
        # Final normalization
        norm = np.linalg.norm(final_vec)
        if norm > 0:
            final_vec = final_vec / norm
            
        return final_vec.astype(np.float16)

def chunk_content(text: str, content_type: str) -> List[str]:
    """Split content into chunks based on type.
    
    Args:
        text: Raw content text.
        content_type: code/text/chapter etc.
        
    Returns:
        List[str]: Chunks under 512 tokens.
    """
    # Placeholder for AST-aware split or paragraph split
    # For now, simple split by lines/paragraphs
    # Code blocks are split by double newlines until AST-aware chunking is added
    # Paragraph-based split
    paragraphs = text.split('\n\n')
    return [p.strip() for p in paragraphs if p.strip()]

def load_content_embedder(config: Any, model_dir: Path) -> ContentEmbedder:
    """Helper to load BGE-M3 from config."""
    model_name = config.models.embedding_content
    path = model_dir / model_name
    return ContentEmbedder(
        model_path=path / "model.onnx",
        tokenizer_path=path / "tokenizer.json"
    )
