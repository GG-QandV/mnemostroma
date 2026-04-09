# SPDX-License-Identifier: FSL-1.1-MIT
"""Cross-encoder reranking using TinyBERT (ONNX)."""
import logging
import os
from typing import List, Tuple

logger = logging.getLogger(__name__)

class TinyBERTReranker:
    """ONNX wrapper for TinyBERT-L2-v2 cross-encoder.
    
    Reranks Top-20 retrieved candidates into Top-5 based on precise relevance.
    """
    def __init__(self, model_path: str, tokenizer_path: str):
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.session = None
        self.tokenizer = None
        self._loaded = False
        
    def _load(self) -> None:
        if self._loaded:
            return
            
        try:
            from onnxruntime import InferenceSession
            from tokenizers import Tokenizer
            
            if not os.path.exists(self.model_path):
                raise FileNotFoundError(f"Reranker ONNX not found at {self.model_path}")
                
            if not os.path.exists(self.tokenizer_path):
                raise FileNotFoundError(f"Reranker Tokenizer not found at {self.tokenizer_path}")
                
            self.session = InferenceSession(self.model_path)
            self.tokenizer = Tokenizer.from_file(self.tokenizer_path)
            self._loaded = True
            logger.info("Successfully loaded TinyBERT Reranker ONNX")
        except Exception as e:
            logger.error(f"Failed to load TinyBERT ONNX: {e}")
            raise

    def rerank(self, query: str, candidates: List[str]) -> List[Tuple[str, float]]:
        """Rerank candidates against query."""
        if not candidates:
            return []
            
        if not self._loaded:
            self._load()
            
        try:
            scores = []
            for doc in candidates:
                # [CLS] query [SEP] doc [SEP]
                pair = f"[CLS] {query} [SEP] {doc} [SEP]"
                tokens = self.tokenizer.encode(pair)
                
                inputs = {
                    "input_ids": [tokens.ids],
                    "attention_mask": [tokens.attention_mask],
                    "token_type_ids": [tokens.type_ids]
                }
                
                # Model output is usually logits [1, 2] or similar regression score [1, 1]
                # Assuming standard cross-encoder softmax over binary classification
                outputs = self.session.run(None, inputs)[0][0]
                
                if len(outputs) > 1:
                    score = float(outputs[1]) # probability of relevant
                else:
                    score = float(outputs[0]) # regression raw score
                    
                scores.append((doc, score))
                
            # Returns sorted pairs (highest score first)
            return sorted(scores, key=lambda x: -x[1])
            
        except Exception as e:
            logger.error(f"Reranking failed: {e}")
            raise
