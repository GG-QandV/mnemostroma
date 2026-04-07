# SPDX-License-Identifier: FSL-1.1-MIT
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from pathlib import Path
from typing import List, Dict, Any

class GLiNER:
    """GLiNER ONNX wrapper for zero-shot Named Entity Recognition."""
    def __init__(self, model_path: str | Path, tokenizer_path: str | Path):
        self.session = ort.InferenceSession(str(model_path))
        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self.entity_types = [
            "decision", "prohibition", "artifact", "technology",
            "concept", "question", "person", "product"
        ]

    async def extract_entities(self, text: str, threshold: float = 0.7) -> List[Dict[str, Any]]:
        """Extract entities from text using zero-shot NER.
        
        Args:
            text: Input text.
            threshold: Confidence threshold for extraction.
            
        Returns:
            List of entities: [{"type": ..., "value": ..., "score": ...}]
        """
        # GLiNER requires specific prompt formatting for zero-shot
        # Simplified placeholder for ONNX inference logic
        # Actual implementation would follow the GLiNER ONNX export spec
        
        # Mocking the process for now:
        # 1. Tokenize text + labels
        # 2. Run session.run
        # 3. Parse spans
        
        return [] # Returns empty list until full ONNX logic is added

def load_ner(config: Any, model_dir: Path) -> GLiNER:
    """Helper to load GLiNER from config."""
    model_name = config.models.ner
    path = model_dir / model_name
    return GLiNER(
        model_path=path / "model.onnx",
        tokenizer_path=path / "tokenizer.json"
    )
