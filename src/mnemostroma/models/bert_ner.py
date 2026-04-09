# SPDX-License-Identifier: FSL-1.1-MIT
"""BertNER: Standard Token Classification for ONNX (No Torch)."""
import logging
import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

class BertNER:
    """Standard BERT-based NER using Token Classification (BIO tags).
    
    Adheres to Mnemostroma Rule 1: No torch, no transformers.
    Supports DistilBERT/BERT int8 ONNX models.
    """
    def __init__(self, model_path: str, tokenizer_path: str):
        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self._session = None
        self._tokenizer = None
        self._id2label = {
            "0": "O",
            "1": "B-DATE", "2": "I-DATE",
            "3": "B-PER", "4": "I-PER",
            "5": "B-ORG", "6": "I-ORG",
            "7": "B-LOC", "8": "I-LOC"
        }
        # Mapping to English labels for pipeline compatibility
        self._label_map = {
            "DATE": "date",
            "PER": "person",
            "ORG": "organization",
            "LOC": "address"
        }

    def load(self) -> None:
        """Initialize ONNX session with memory-safe options (Rule 5)."""
        opts = ort.SessionOptions()
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        
        self._session = ort.InferenceSession(self.model_path, opts)
        self._tokenizer = Tokenizer.from_file(self.tokenizer_path)
        logger.info(f"BertNER loaded model: {self.model_path}")

    def predict_entities(self, text: str, threshold: float = 0.5) -> List[Dict[str, Any]]:
        """Predict and structure entities from text."""
        if self._session is None:
            self.load()

        encoded = self._tokenizer.encode(text)
        input_ids = np.array([encoded.ids], dtype=np.int64)
        attention_mask = np.array([encoded.attention_mask], dtype=np.int64)

        # 1. Inference
        feed = {
            "input_ids": input_ids,
            "attention_mask": attention_mask
        }
        
        # Check if model requires token_type_ids
        sess_input_names = [i.name for i in self._session.get_inputs()]
        if "token_type_ids" in sess_input_names:
            feed["token_type_ids"] = np.array([encoded.type_ids], dtype=np.int64)
            
        outputs = self._session.run(None, feed)
        logits = outputs[0][0]  # [seq_len, num_labels]
        
        # 2. Softmax (simplified for top-1)
        probs = self._softmax(logits)
        predictions = np.argmax(probs, axis=-1)
        scores = np.max(probs, axis=-1)

                # 3. Span Reconstruction (BIO to Spans)
        entities = []
        current_entity = None

        for i, (pred_id, score) in enumerate(zip(predictions, scores)):
            # Skip special tokens [CLS], [SEP]
            if i == 0 or i == len(encoded.ids) - 1:
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None
                continue

            label = self._id2label.get(str(pred_id), "O")
            
            if label == "O":
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None
                continue

            bio, ent_type = label.split("-")
            ru_type = self._label_map.get(ent_type, ent_type)
            start, end = encoded.offsets[i]
            
            # Check if this token is a subword (## prefix or same word_id)
            is_subword = encoded.tokens[i].startswith("##")

            if bio == "B" and not is_subword:
                # New entity starts
                if current_entity:
                    entities.append(current_entity)
                current_entity = {
                    "type": ru_type,
                    "value": text[start:end],
                    "score": float(score),
                    "start": int(start),
                    "end": int(end)
                }
            elif bio == "I" and current_entity and current_entity["type"] == ru_type:
                # Continue existing entity
                current_entity["value"] = text[current_entity["start"]:end]
                current_entity["end"] = int(end)
                current_entity["score"] = min(current_entity["score"], float(score))
            elif bio == "I" and is_subword and current_entity:
                # Subword continues previous entity regardless of type mismatch
                current_entity["value"] = text[current_entity["start"]:end]
                current_entity["end"] = int(end)
                current_entity["score"] = min(current_entity["score"], float(score))
            else:
                # Orphan I-tag without matching B — discard
                if current_entity:
                    entities.append(current_entity)
                    current_entity = None

        if current_entity:
            entities.append(current_entity)

        # 4. Post-processing
        result = []
        for e in entities:
            if e["score"] < threshold:
                continue
            e["value"] = e["value"].strip()
            if len(e["value"]) <= 1:
                continue
            result.append(e)
        return result

        # 4. Post-processing: filter by threshold and clean fragments
        result = []
        for e in entities:
            if e["score"] < threshold:
                continue
            # Strip whitespace from value
            e["value"] = e["value"].strip()
            # Skip empty or single-char fragments (subword artifacts)
            if len(e["value"]) <= 1:
                continue
            result.append(e)
        return result

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        """Standard Softmax over logits."""
        e_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
        return e_x / e_x.sum(axis=-1, keepdims=True)

    def close(self) -> None:
        """Release ONNX session resources."""
        self._session = None
        self._tokenizer = None
