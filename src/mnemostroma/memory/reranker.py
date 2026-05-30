# SPDX-License-Identifier: FSL-1.1-MIT
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer


class Reranker:
    """TinyBERT ONNX wrapper for cross-encoder reranking.
    
    Provides precise relevance scoring for (query, document) pairs.
    """
    def __init__(self, model_path: str | Path, tokenizer_path: str | Path):
        self.session = ort.InferenceSession(str(model_path))
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def rank(self, query: str, documents: list[str]) -> list[float]:
        """Rank a list of documents against a query.
        
        Args:
            query: The search query.
            documents: List of document summaries/briefs to rank.
            
        Returns:
            List of relevance scores (0.0 to 1.0).
        """
        # Cross-encoders expect [CLS] query [SEP] doc [SEP]
        scores = []
        for doc in documents:
            encoded = self.tokenizer.encode(query, doc)
            input_ids = np.array([encoded.ids], dtype=np.int64)
            attention_mask = np.array([encoded.attention_mask], dtype=np.int64)
            token_type_ids = np.array([encoded.type_ids], dtype=np.int64)
            
            inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": token_type_ids
            }
            
            outputs = self.session.run(None, inputs)
            # outputs[0] shape: (1, 1) → flatten to scalar before sigmoid
            logit = float(np.squeeze(outputs[0]))
            score = 1.0 / (1.0 + np.exp(-logit))
            scores.append(float(score))
            
        return scores

def load_reranker(config: Any, model_dir: Path) -> Reranker:
    """Helper to load TinyBERT from config."""
    model_name = config.models.reranker
    path = model_dir / model_name
    return Reranker(
        model_path=path / "model.onnx",
        tokenizer_path=path / "tokenizer.json"
    )
