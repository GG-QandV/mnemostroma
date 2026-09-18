# SPDX-License-Identifier: FSL-1.1-MIT
"""Span decoding for GLiNER, on numpy.

Why this exists: the upstream decoder (`gliner/decoding/decoder.py`, 2076 lines) is
built on torch, and the runtime rule of this project is ONNX only — no torch, no
transformers in the installed package. This is a port of the one branch we use:
uni-encoder span decoding, single sample, no generative labels, no relations.

Ported from GLiNER 0.2.28 (`BaseSpanDecoder._decode_single`, `greedy_search`,
`decoding/utils.py`). Behaviour is meant to match it exactly; the tests pin the
parts where a silent divergence would be hard to notice — the `+1` class offset
and the overlap rules.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class Span:
    """One decoded entity, in WORD indices (inclusive on both ends)."""

    start: int
    end: int
    entity_type: str
    score: float


def _sigmoid(x: np.ndarray) -> np.ndarray:
    """Numerically stable sigmoid — logits reach ±700 and np.exp overflows."""
    out = np.empty_like(x, dtype=np.float32)
    pos = x >= 0
    out[pos] = 1.0 / (1.0 + np.exp(-x[pos]))
    exp_x = np.exp(x[~pos])
    out[~pos] = exp_x / (1.0 + exp_x)
    return out


def is_nested(a: tuple[int, int], b: tuple[int, int]) -> bool:
    """True when one span fully contains the other."""
    return (a[0] <= b[0] and a[1] >= b[1]) or (b[0] <= a[0] and b[1] >= a[1])


def has_overlapping(a: tuple, b: tuple, multi_label: bool = False) -> bool:
    """Flat NER: any overlap counts, including an identical span."""
    if a[:2] == b[:2]:
        return not multi_label
    return not (a[0] > b[1] or b[0] > a[1])


def has_overlapping_nested(a: tuple, b: tuple, multi_label: bool = False) -> bool:
    """Nested NER: overlap counts only when neither span contains the other."""
    if a[:2] == b[:2]:
        return not multi_label
    return not ((a[0] > b[1] or b[0] > a[1]) or is_nested(a, b))


def greedy_search(
    spans: list[Span], flat_ner: bool = True, multi_label: bool = False
) -> list[Span]:
    """Keep the highest-scoring spans that do not conflict, then order by position."""
    if not spans:
        return []

    conflicts = has_overlapping if flat_ner else has_overlapping_nested

    kept: list[Span] = []
    kept_tuples: list[tuple] = []
    for span in sorted(spans, key=lambda s: -s.score):
        candidate = (span.start, span.end, span.entity_type)
        if any(conflicts(candidate, other, multi_label) for other in kept_tuples):
            continue
        kept.append(span)
        kept_tuples.append(candidate)

    kept.sort(key=lambda s: s.start)
    return kept


def decode_spans(
    logits: np.ndarray,
    num_words: int,
    id_to_class: dict[int, str],
    threshold: float = 0.5,
    flat_ner: bool = True,
    multi_label: bool = False,
) -> list[Span]:
    """Turn raw span logits into entities.

    Args:
        logits: (L, K, C) for one sample — start position × span width × class.
            A (1, L, K, C) batch of one is accepted and squeezed.
        num_words: words in the sample; spans running past it are dropped.
        id_to_class: 1-based class ids, as GLiNER stores them (0 is <pad>).
        threshold: minimum probability after sigmoid.
        flat_ner: True forbids any overlap, False allows nesting.
        multi_label: True lets one span carry several types.
    """
    if logits.ndim == 4:
        if logits.shape[0] != 1:
            raise ValueError(f"expected a single sample, got batch of {logits.shape[0]}")
        logits = logits[0]
    if logits.ndim != 3:
        raise ValueError(f"expected (L, K, C) logits, got shape {logits.shape}")

    probs = _sigmoid(np.asarray(logits, dtype=np.float32))
    starts, widths, classes = np.nonzero(probs > threshold)
    if starts.size == 0:
        return []

    # end = start + width; a span may not run past the last word.
    valid = (starts + widths + 1) <= num_words
    starts, widths, classes = starts[valid], widths[valid], classes[valid]
    if starts.size == 0:
        return []

    scores = probs[starts, widths, classes]

    spans: list[Span] = []
    for start, width, class_idx, score in zip(starts, widths, classes, scores):
        # +1: class ids in the manifest are 1-based, index 0 is <pad>.
        entity_type = id_to_class.get(int(class_idx) + 1)
        if entity_type is None:
            # Unknown class id means the type list and the graph disagree — that
            # is a wiring bug, and skipping it silently would hide it.
            raise ValueError(
                f"class id {int(class_idx) + 1} is not in id_to_class "
                f"(known: {sorted(id_to_class)})"
            )
        spans.append(
            Span(
                start=int(start),
                end=int(start + width),
                entity_type=entity_type,
                score=float(score),
            )
        )

    return greedy_search(spans, flat_ner=flat_ner, multi_label=multi_label)


# Types whose parts are meaningless on their own. A date split into "15 марта" and
# "2027" puts a bare year into memory as an entity of its own, which is worse than
# missing the date: it looks like a fact and is not one. Measured on real weights —
# round 14, Q-2.
_STITCHABLE_TYPES = frozenset({"date"})


def stitch_adjacent_spans(
    spans: list[Span], stitchable: frozenset[str] = _STITCHABLE_TYPES
) -> list[Span]:
    """Join word-adjacent spans of the same stitchable type into one.

    Adjacency is in WORD indices, so anything between the parts stops the join —
    the tokeniser makes punctuation its own word, and "3 мая, 2026" therefore stays
    two spans while "15 марта 2027" becomes one.

    The score of the joined span is the lower of the two: a span is only as certain
    as its least certain half, and taking the max would inflate confidence in exactly
    the case where the model was unsure enough to split.
    """
    if not spans:
        return []

    ordered = sorted(spans, key=lambda s: (s.start, s.end))
    merged: list[Span] = [ordered[0]]
    for span in ordered[1:]:
        last = merged[-1]
        if (
            span.entity_type == last.entity_type
            and span.entity_type in stitchable
            and span.start == last.end + 1
        ):
            merged[-1] = Span(
                start=last.start,
                end=span.end,
                entity_type=last.entity_type,
                score=min(last.score, span.score),
            )
        else:
            merged.append(span)
    return merged


def spans_to_entities(
    spans: list[Span],
    word_offsets: list[tuple[int, int]],
    text: str,
) -> list[dict]:
    """Convert word-index spans into the entity dicts the Observer pipeline expects.

    Same shape as `HybridNER.extract_entities` returns: type, value, score and
    character offsets, so downstream code (anchors, key_facts, mention_type) needs
    no changes.
    """
    entities: list[dict] = []
    for span in spans:
        if span.start >= len(word_offsets) or span.end >= len(word_offsets):
            # Offsets and spans came from different tokenisations — a real bug,
            # and a truncated entity would be worse than a loud failure.
            raise ValueError(
                f"span ({span.start},{span.end}) outside word_offsets "
                f"of length {len(word_offsets)}"
            )
        char_start = word_offsets[span.start][0]
        char_end = word_offsets[span.end][1]
        entities.append(
            {
                "type": span.entity_type,
                "value": text[char_start:char_end],
                "score": span.score,
                "start": char_start,
                "end": char_end,
            }
        )
    return entities
