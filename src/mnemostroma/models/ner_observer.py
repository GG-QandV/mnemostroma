# SPDX-License-Identifier: FSL-1.1-MIT
"""NER extraction using Standard BERT/DistilBERT ONNX (No Torch)."""
import gc
import logging
from typing import List, Dict, Any

from .hybrid_ner import HybridNER

logger = logging.getLogger(__name__)

class NERObserver:
    """Standard NER extractor using HybridNER (BERT + Regex).
    
    Adheres to Mnemostroma Rule 1: No torch, no transformers.
    Optimized for DistilBERT int8 models in 700MB budget environments.
    """
    def __init__(self, model_path: str, tokenizer_path: str):
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self.model = HybridNER(model_path, tokenizer_path)
        self._loaded = False
        
    def _load(self) -> None:
        """Initialize the HybridNER session."""
        if self._loaded:
            return
            
        try:
            self.model.load()
            self._loaded = True
            logger.info("Successfully loaded HybridNER (ONNX + Regex)")
        except Exception as e:
            logger.error(f"Failed to load HybridNER: {e}")
            raise

    async def extract_entities(self, text: str, threshold: float = 0.5) -> List[Dict[str, Any]]:
        """Extract entities from text using HybridNER.
        
        Interface is async and uses executor for CPU-bound parts.
        """
        if not self._loaded:
            self._load()
            
        try:
            # HybridNER.extract_entities is already async and uses executor
            entities = await self.model.extract_entities(text, threshold=threshold)
            return entities
        except Exception as e:
            logger.error(f"HybridNER extraction failed: {e}")
            raise

    def unload(self) -> None:
        """Release ONNX session after observer run to free ~200 MB in idle."""
        if not self._loaded:
            return
        self.model.close()
        self._loaded = False
        gc.collect()
        logger.debug("NERObserver unloaded (ONNX session released)")

# For backward compatibility during migration
GLiNERObserver = NERObserver
