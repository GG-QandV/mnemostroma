# SPDX-License-Identifier: FSL-1.1-MIT
"""GLiNER inference over ONNX Runtime, without torch.

Zero-shot NER: the entity types are part of the input, so the same weights serve
`person`/`organization` and Mnemostroma's own `decision`/`prohibition`/`technology`
(`observer/ner.py:14-17`). Types cost almost nothing — measured 3 vs 8 types differ
by ~100 ms, because they ride in one prompt rather than one pass each.

Input contract is the upstream export spec (GLiNER 0.2.28,
`UniEncoderSpanGLiNER._get_onnx_input_spec`): `input_ids`, `attention_mask`,
`words_mask`, `text_lengths`, `span_idx`, `span_mask` → `logits` (B, words, width, types).
It is verified against the loaded graph, because a mismatch here produces plausible
garbage rather than an error.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from . import footprint
from .gliner_decode import decode_spans, spans_to_entities, stitch_adjacent_spans

logger = logging.getLogger(__name__)

# Upstream WhitespaceTokenSplitter: words, keeping hyphenated and underscored ones whole.
_WORD_PATTERN = re.compile(r"\w+(?:[-_]\w+)*|\S")

EXPECTED_INPUTS = (
    "input_ids",
    "attention_mask",
    "words_mask",
    "text_lengths",
    "span_idx",
    "span_mask",
)


def split_words(text: str) -> list[tuple[str, int, int]]:
    """Split into words with character offsets, as upstream does."""
    return [(m.group(), m.start(), m.end()) for m in _WORD_PATTERN.finditer(text)]


def build_prompt(entity_types: list[str], ent_token: str, sep_token: str) -> list[str]:
    """`[ENT] type1 [ENT] type2 ... [SEP]` — the prompt the model reads as its label set."""
    prompt: list[str] = []
    for entity_type in entity_types:
        prompt.append(ent_token)
        prompt.append(str(entity_type))
    prompt.append(sep_token)
    return prompt


def build_words_mask(word_ids: list[int | None], prompt_len: int) -> list[int]:
    """Map subtokens back to text words, 1-indexed; 0 means "ignore".

    Only the FIRST subtoken of each word carries its index (`subtoken_pooling:
    first`). Prompt words and special tokens are zeroed, so the model pools over
    the text alone.
    """
    mask: list[int] = []
    previous = None
    for word_id in word_ids:
        if word_id is None or word_id < prompt_len:
            mask.append(0)
        elif word_id == previous:
            mask.append(0)          # continuation subtoken
        else:
            mask.append(word_id - prompt_len + 1)
        previous = word_id
    return mask


def build_spans(num_words: int, max_width: int) -> tuple[np.ndarray, np.ndarray]:
    """Every candidate span up to `max_width`, plus a mask for the ones that fit.

    Shapes follow the export spec: span_idx (1, num_words * max_width, 2),
    span_mask (1, num_words * max_width). Both ends are inclusive.
    """
    starts = np.repeat(np.arange(num_words, dtype=np.int64), max_width)
    widths = np.tile(np.arange(max_width, dtype=np.int64), num_words)
    ends = starts + widths
    span_idx = np.stack([starts, ends], axis=-1)[np.newaxis, ...]
    # bool, not int64: the exported graph declares span_mask as tensor(bool) and ORT
    # rejects an int64 feed outright (upstream collator uses torch.bool).
    span_mask = (ends < num_words)[np.newaxis, ...]
    return span_idx, span_mask


class GLiNEREngine:
    """ONNX GLiNER: text plus a list of types in, entity dicts out."""

    def __init__(
        self,
        model_path: str | Path,
        tokenizer_path: str | Path,
        max_width: int = 12,
        max_length: int = 512,
        ent_token: str = "<<ENT>>",
        sep_token: str = "<<SEP>>",
        # Only a fallback: the pipeline passes config.importance.ner_score_threshold
        # (0.5 shipped), and measurements taken at 0.3 include spans production never
        # sees — most of the "noise" types scored 0.31-0.49.
        threshold: float = 0.3,
        flat_ner: bool = True,
        graph_optimization_level: str | None = None,
        disable_prepacking: bool = False,
        threads: int = 0,
        intra_threads: int = 0,
    ):
        self._model_path = str(model_path)
        self._max_width = max_width
        self._max_length = max_length
        self._ent_token = ent_token
        self._sep_token = sep_token
        self._threshold = threshold
        self._flat_ner = flat_ner

        opts = ort.SessionOptions()
        # 0 = let ORT choose, which is what upstream runs. Capping the threads changes
        # how INT8 kernels partition and accumulate: measured max |delta logits| 2.29
        # against upstream at 1/1, 2/2 and 4/8 alike, and 0.0 at the default.
        if threads:
            opts.inter_op_num_threads = threads
        if intra_threads:
            opts.intra_op_num_threads = intra_threads
        opts.enable_cpu_mem_arena = False
        opts.enable_mem_pattern = False
        # ORT_DISABLE_ALL: 179 MB cheaper (241 vs 420) for an identical output.
        #
        # This default was set once on an assumption, broke parity and was reverted
        # (d4c531c -> ac57507). It comes back on measurements (round 14):
        #   * with the SAME session options on both sides, our engine matches upstream
        #     at either level — 1.19e-07 at ENABLE_ALL 0/0, DISABLE_ALL 0/0 and
        #     DISABLE_ALL 2/2 alike. The port is correct either way (Q-1);
        #   * against the fp32 graph, the two INT8 levels extract exactly the same
        #     entities — 0 differences, 0 spans crossing the threshold (Q-2).
        # So the level is not a correctness knob here; it is memory against latency:
        # p50 107 / 281 / 1169 ms versus 59 / 134 / 845 on 30 / 128 / 512 tokens.
        # Memory wins because it is permanent — 179 MB sit in RSS for the life of the
        # process and push the Dissolver into evicting sessions — while the latency is
        # paid only when the NER gate lets the model run.
        #
        # Parity is a property of artefact + inputs + session options. Comparing this
        # default against upstream at ITS default (ENABLE_ALL) shows a 8.4e-02 score
        # gap that means nothing: both sides must be configured alike (round 13).
        level_name = graph_optimization_level or "ORT_DISABLE_ALL"
        try:
            opts.graph_optimization_level = getattr(ort.GraphOptimizationLevel, level_name)
        except AttributeError:
            raise ValueError(f"Unknown graph_optimization_level: {level_name!r}") from None
        if disable_prepacking:
            opts.add_session_config_entry("session.disable_prepacking", "1")

        self._footprint_key = f"gliner:{self._model_path}"
        with footprint.measure(self._footprint_key):
            self.session = ort.InferenceSession(
                self._model_path, opts, providers=["CPUExecutionProvider"]
            )

        graph_inputs = {i.name for i in self.session.get_inputs()}
        missing = set(EXPECTED_INPUTS) - graph_inputs
        if missing:
            # Feeding a differently-exported graph produces plausible spans rather
            # than an error, so the mismatch has to stop us here.
            raise ValueError(
                f"GLiNER graph is missing inputs {sorted(missing)}; "
                f"it exposes {sorted(graph_inputs)}. Expected the uni-encoder span "
                f"export ({', '.join(EXPECTED_INPUTS)})."
            )

        self.tokenizer = Tokenizer.from_file(str(tokenizer_path))
        logger.info(
            "gliner.create | model=%s max_width=%d opt=%s",
            Path(self._model_path).name, max_width, level_name,
        )

    def extract_entities(
        self,
        text: str,
        entity_types: list[str],
        threshold: float | None = None,
    ) -> list[dict]:
        """Entity dicts in the same shape `HybridNER.extract_entities` returns."""
        if not text.strip() or not entity_types:
            return []

        words = split_words(text)
        if not words:
            return []

        prompt = build_prompt(entity_types, self._ent_token, self._sep_token)
        sequence = prompt + [w for w, _, _ in words]

        self.tokenizer.enable_truncation(max_length=self._max_length)
        encoded = self.tokenizer.encode(sequence, is_pretokenized=True)

        words_mask = build_words_mask(list(encoded.word_ids), len(prompt))
        num_words = max(words_mask)
        if num_words == 0:
            # The prompt alone filled the window — no text words survived truncation.
            return []

        span_idx, span_mask = build_spans(num_words, self._max_width)
        feed = {
            "input_ids": np.array([encoded.ids], dtype=np.int64),
            "attention_mask": np.array([encoded.attention_mask], dtype=np.int64),
            "words_mask": np.array([words_mask], dtype=np.int64),
            "text_lengths": np.array([[num_words]], dtype=np.int64),
            "span_idx": span_idx,
            "span_mask": span_mask,
        }
        logits = self.session.run(None, feed)[0]

        id_to_class = {i + 1: t for i, t in enumerate(entity_types)}
        spans = decode_spans(
            logits,
            num_words=num_words,
            id_to_class=id_to_class,
            threshold=self._threshold if threshold is None else threshold,
            flat_ner=self._flat_ner,
        )
        # The model splits "15 марта 2027" into two date spans (round 14, Q-2); a bare
        # "2027" in memory reads as a fact it is not.
        spans = stitch_adjacent_spans(spans)
        # Truncation can leave fewer words than the text has; clip the offsets to match.
        return spans_to_entities(spans, [(s, e) for _, s, e in words[:num_words]], text)

    def close(self) -> None:
        self.session = None
        footprint.release(self._footprint_key)
