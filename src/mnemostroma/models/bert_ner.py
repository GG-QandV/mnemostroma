# SPDX-License-Identifier: FSL-1.1-MIT
"""BertNER: Standard Token Classification for ONNX (No Torch)."""
import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from . import footprint

logger = logging.getLogger(__name__)

_DEFAULT_ID2LABEL: dict[str, str] = {
    "0": "O",
    "1": "B-DATE", "2": "I-DATE",
    "3": "B-PER", "4": "I-PER",
    "5": "B-ORG", "6": "I-ORG",
    "7": "B-LOC", "8": "I-LOC",
}


def _read_id2label(model_path: str) -> tuple[dict[str, str], str] | None:
    """Read `id2label` from the model's own config.json.

    Looked up next to the weights and one level up, which covers both layouts we
    ship: `<model>/config.json` and `<model>/onnx/model_int8.onnx`.
    """
    weights = Path(model_path)
    for candidate in (weights.parent / "config.json", weights.parent.parent / "config.json"):
        if not candidate.exists():
            continue
        try:
            with open(candidate, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("id2label: cannot read %s: %s", candidate, e)
            continue
        mapping = data.get("id2label")
        if isinstance(mapping, dict) and mapping:
            return {str(k): str(v) for k, v in mapping.items()}, str(candidate)
    return None


class BertNER:
    """Standard BERT-based NER using Token Classification (BIO tags).
    
    Adheres to Mnemostroma Rule 1: No torch, no transformers.
    Supports DistilBERT/BERT int8 ONNX models.
    """
    _instances_created: int = 0
    _instances_lock = threading.Lock()

    def __init__(
        self,
        model_path: str,
        tokenizer_path: str,
        graph_optimization_level: str | None = None,
        disable_prepacking: bool = False,
    ):
        with self._instances_lock:
            type(self)._instances_created += 1
            self._instance_id = type(self)._instances_created

        logger.warning(
            "BertNER instance created id=%d pid=%d",
            self._instance_id,
            os.getpid(),
            stack_info=True,
        )

        self.model_path = model_path
        self.tokenizer_path = tokenizer_path
        self._graph_optimization_level = graph_optimization_level
        self._disable_prepacking = disable_prepacking
        self._session: ort.InferenceSession | None = None
        self._session_lock = threading.Lock()
        self._load_count = 0
        self._tokenizer = None
        # Fallback for Davlan/distilbert-base-multilingual-cased-ner-hrl. Any other
        # checkpoint has its own label order, and reusing this one would shift every
        # id — PER read as DATE, ORG as PER — without a single error. The real map is
        # read from the model's config.json in _load(); this is only the last resort.
        self._id2label = _DEFAULT_ID2LABEL.copy()
        self._id2label_source = "builtin-default"
        # Mapping to Mnemostroma labels for pipeline compatibility
        self._label_map = {
            "DATE": "date",
            "PER": "person",
            "ORG": "organization",
            "LOC": "address"
        }

    def _session_options(self) -> ort.SessionOptions:
        opts = ort.SessionOptions()
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        # ORT_ENABLE_ALL fuses Gather+LayerNorm into EmbedLayerNormalization, which
        # materialises low-bit embedding tables in fp32 (measured: +486 MB on an INT4
        # encoder). Models that pay that price opt out via the manifest.
        level_name = self._graph_optimization_level or "ORT_ENABLE_ALL"
        try:
            opts.graph_optimization_level = getattr(ort.GraphOptimizationLevel, level_name)
        except AttributeError:
            raise ValueError(f"Unknown graph_optimization_level: {level_name!r}") from None
        if self._disable_prepacking:
            opts.add_session_config_entry("session.disable_prepacking", "1")
        return opts

    def load(self) -> None:
        """Initialize ONNX session with memory-safe options (Rule 5).

        Idempotent: safe to call multiple times. Thread-safe via lock.
        """
        if self._session is not None:
            return

        with self._session_lock:
            if self._session is not None:
                return

            with footprint.measure(f"ner:{self.model_path}"):
                self._session = ort.InferenceSession(
                    self.model_path,
                    sess_options=self._session_options(),
                    providers=["CPUExecutionProvider"],
                )
            self._tokenizer = Tokenizer.from_file(self.tokenizer_path)
            self._tokenizer.enable_truncation(max_length=512)

            found = _read_id2label(self.model_path)
            if found is not None:
                self._id2label, self._id2label_source = found
            logger.info(
                "BertNER labels | count=%d source=%s",
                len(self._id2label), self._id2label_source,
            )

            self._load_count += 1
            logger.warning(
                "BertNER session created: count=%d pid=%d",
                self._load_count, os.getpid(),
                stack_info=True,
            )

    def predict_entities(self, text: str, threshold: float = 0.5) -> list[dict[str, Any]]:
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

        # A label map that does not match the model is the worst failure mode here:
        # every id shifts and entities come out confidently mislabelled, with no error
        # anywhere. Catch it on the first run instead.
        if logits.shape[-1] != len(self._id2label):
            raise ValueError(
                f"NER label map mismatch: model emits {logits.shape[-1]} labels, "
                f"map has {len(self._id2label)} (source: {self._id2label_source}). "
                f"Add id2label to the model's config.json."
            )
        
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

            # Labels must be BIO ("B-PER"). Checkpoints that ship an unfilled
            # id2label give "LABEL_3" instead, and a bare split() would raise a
            # ValueError with no hint of the real cause halfway through a batch.
            bio, _, ent_type = label.partition("-")
            if bio not in ("B", "I") or not ent_type:
                raise ValueError(
                    f"NER label {label!r} is not in BIO format (source: "
                    f"{self._id2label_source}). The checkpoint ships no usable "
                    f"id2label — add one to its config.json."
                )
            mapped_type = self._label_map.get(ent_type, ent_type)
            start, end = encoded.offsets[i]
            
            # Check if this token is a subword (## prefix or same word_id)
            is_subword = encoded.tokens[i].startswith("##")

            if bio == "B" and not is_subword:
                # New entity starts
                if current_entity:
                    entities.append(current_entity)
                current_entity = {
                    "type": mapped_type,
                    "value": text[start:end],
                    "score": float(score),
                    "start": int(start),
                    "end": int(end)
                }
            elif bio == "I" and current_entity and current_entity["type"] == mapped_type:
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

    def _softmax(self, x: np.ndarray) -> np.ndarray:
        """Standard Softmax over logits."""
        e_x = np.exp(x - np.max(x, axis=-1, keepdims=True))
        return e_x / e_x.sum(axis=-1, keepdims=True)

    def close(self, *, shutdown: bool = False) -> None:
        """Release ONNX session resources. Shutdown-only.

        Calling close() outside Application.shutdown() will raise
        RuntimeError — the session must not be torn down mid-lifecycle.
        """
        logger.error(
            "BertNER.close called: shutdown=%s pid=%d",
            shutdown, os.getpid(),
            stack_info=True,
        )
        if not shutdown:
            raise RuntimeError("Unexpected BertNER.close outside shutdown")
        self._session = None
        self._tokenizer = None
        footprint.release(f"ner:{self.model_path}")
