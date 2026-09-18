# SPDX-License-Identifier: FSL-1.1-MIT
"""Embedding utilities — chunking and multi-chunk aggregation.

Engine-agnostic: works with any EmbeddingEngine implementation.
"""
import logging
import re
from typing import TYPE_CHECKING, Callable

import numpy as np

if TYPE_CHECKING:
    from .protocol import EmbeddingEngine

logger = logging.getLogger(__name__)

# Target size of one chunk, in tokens of the active embedder. 384 sits in the middle
# of the 256-512 range the ADR settled on and leaves headroom under the 512-token
# window for a query prefix. Overlap keeps a sentence that straddles a boundary
# retrievable from both sides.
DEFAULT_TARGET_TOKENS = 384
DEFAULT_OVERLAP_TOKENS = 48

# Roughly 3.5 characters per token across the languages this project sees. Used only
# when no tokenizer is available; it is an order-of-magnitude guard, not a measurement.
_CHARS_PER_TOKEN = 3.5

_PARAGRAPH_RE = re.compile(r"\n\s*\n")
# Sentence end followed by whitespace. Keeps the terminator with the sentence it ends.
_SENTENCE_RE = re.compile(r"(?<=[.!?…])\s+|(?<=[.!?…][\"\'»)])\s+")
# Top-level definitions: where a code file can be cut without splitting a function.
_CODE_BOUNDARY_RE = re.compile(
    r"\n(?=(?:@|def |class |async def |func |function |public |private |"
    r"protected |static |impl |fn |type |const |var |let )\S)"
)


def _heuristic_token_count(text: str) -> int:
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def make_token_counter(tokenizer) -> Callable[[str], int]:
    """Count tokens with the embedder's own tokenizer, so boundaries match its window.

    The engine leaves `enable_truncation` set on its tokenizer, so a very long string
    comes back capped rather than counted. That is harmless here: anything reported at
    or above the target is split further anyway, and every count we actually add up
    belongs to a fragment already known to be shorter than the cap.
    """
    if tokenizer is None:
        return _heuristic_token_count

    def count(text: str) -> int:
        try:
            return len(tokenizer.encode(text, add_special_tokens=False).ids)
        except Exception:      # noqa: BLE001 - a tokenizer failure must not lose content
            logger.warning("token count failed, falling back to the char heuristic")
            return _heuristic_token_count(text)

    return count


def _split_oversized(atom: str, count: Callable[[str], int], target: int) -> list[str]:
    """Cut a fragment that alone exceeds the target, on the widest boundary available.

    Words first; a word that is still too long (a base64 blob, a minified line) is cut
    by characters. Losing content is not an option, so the last resort always cuts.
    """
    pieces: list[str] = []
    buffer: list[str] = []
    for word in atom.split():
        buffer.append(word)
        if count(" ".join(buffer)) >= target:
            buffer.pop()
            if buffer:
                pieces.append(" ".join(buffer))
                buffer = [word]
            else:
                # One word over the target: cut it by characters.
                limit = max(1, int(target * _CHARS_PER_TOKEN))
                pieces.extend(word[i:i + limit] for i in range(0, len(word), limit))
                buffer = []
    if buffer:
        pieces.append(" ".join(buffer))
    return pieces or [atom]


def _atoms(text: str, content_type: str, count: Callable[[str], int], target: int) -> list[str]:
    """Break text into the smallest units the packer is allowed to move around."""
    if content_type == "code":
        coarse = [p for p in _CODE_BOUNDARY_RE.split(text) if p.strip()]
    else:
        coarse = [p for p in _PARAGRAPH_RE.split(text) if p.strip()]

    atoms: list[str] = []
    for part in coarse:
        part = part.strip()
        if count(part) < target:
            atoms.append(part)
            continue
        # Too big to place whole: go finer. Sentences for prose, lines for code.
        finer = (
            [ln for ln in part.split("\n") if ln.strip()]
            if content_type == "code"
            else [s for s in _SENTENCE_RE.split(part) if s.strip()]
        )
        for piece in finer:
            piece = piece.strip()
            if count(piece) < target:
                atoms.append(piece)
            else:
                atoms.extend(_split_oversized(piece, count, target))
    return atoms


def _tail_for_overlap(chunk_atoms: list[str], count: Callable[[str], int], overlap: int) -> list[str]:
    """The trailing atoms worth about `overlap` tokens, to repeat in the next chunk."""
    if overlap <= 0:
        return []
    tail: list[str] = []
    total = 0
    for atom in reversed(chunk_atoms):
        atom_tokens = count(atom)
        if total + atom_tokens > overlap and tail:
            break
        tail.insert(0, atom)
        total += atom_tokens
    # Repeating the whole chunk would make the next one a duplicate of it.
    return [] if len(tail) == len(chunk_atoms) else tail


def chunk_content(
    text: str,
    content_type: str = "text",
    tokenizer=None,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
) -> list[str]:
    """Split content into chunks that fit the embedder's window.

    Splitting used to be `text.split("\n\n")`, which counted no tokens at all: a long
    paragraph became one chunk, the encoder truncated it at 512 tokens and the rest of
    the text was never embedded. Boundaries are now counted in the tokens the model
    actually sees, so truncation goes back to being a last-resort guard.

    Args:
        text: Raw content text.
        content_type: "code" cuts on definitions and lines, anything else on
            paragraphs and sentences.
        tokenizer: The active embedder's tokenizer. Without it, a character heuristic
            is used — enough to keep chunks in range, not enough to be exact.
        target_tokens: Upper bound for one chunk.
        overlap_tokens: How much of the previous chunk to repeat, so a sentence on a
            boundary stays retrievable from both sides.

    Returns:
        List of non-empty text chunks, in order.
    """
    if not text or not text.strip():
        return []

    count = make_token_counter(tokenizer)
    atoms = _atoms(text, content_type, count, target_tokens)
    if not atoms:
        return []

    chunks: list[str] = []
    current: list[str] = []
    current_tokens = 0

    for atom in atoms:
        atom_tokens = count(atom)
        if current and current_tokens + atom_tokens > target_tokens:
            chunks.append("\n\n".join(current))
            carry = _tail_for_overlap(current, count, overlap_tokens)
            current = list(carry)
            current_tokens = sum(count(a) for a in carry)
        current.append(atom)
        current_tokens += atom_tokens

    if current:
        chunks.append("\n\n".join(current))

    logger.debug(
        "chunk_content | type=%s atoms=%d chunks=%d tokenizer=%s",
        content_type, len(atoms), len(chunks), "real" if tokenizer else "heuristic",
    )
    return chunks


def encode_chunks(
    engine: "EmbeddingEngine",
    chunks: list[str],
    decay: float = 0.2,
    min_weight: float = 0.2,
) -> np.ndarray:
    """Encode multiple chunks and aggregate via weighted mean pooling.
    
    First chunk gets weight 1.0, each subsequent decays by `decay`.
    Minimum weight clamped to `min_weight`.
    
    Args:
        engine: Any EmbeddingEngine instance.
        chunks: Text chunks to encode.
        decay: Weight decay per chunk position.
        min_weight: Minimum weight floor.
        
    Returns:
        Normalized float16 vector of shape (engine.dim,).
    """
    if not chunks:
        return np.zeros(engine.dim, dtype=np.float16)
    
    vectors = []
    for i, chunk in enumerate(chunks):
        vec = engine.encode(chunk)
        weight = max(min_weight, 1.0 - (i * decay))
        vectors.append(vec.astype(np.float32) * weight)
        
        logger.debug(
            "encode_chunks | chunk=%d/%d weight=%.1f",
            i + 1, len(chunks), weight,
        )
    
    aggregated = np.mean(vectors, axis=0)
    
    # L2 normalize
    norm = np.linalg.norm(aggregated)
    if norm > 0:
        aggregated = aggregated / norm
    
    return aggregated.astype(np.float16)


async def aencode_chunks(
    engine: "EmbeddingEngine",
    chunks: list[str],
    decay: float = 0.2,
    min_weight: float = 0.2,
) -> np.ndarray:
    """Async version of encode_chunks."""
    if not chunks:
        return np.zeros(engine.dim, dtype=np.float16)
    
    vectors = []
    for i, chunk in enumerate(chunks):
        vec = await engine.aencode(chunk)
        weight = max(min_weight, 1.0 - (i * decay))
        vectors.append(vec.astype(np.float32) * weight)
    
    aggregated = np.mean(vectors, axis=0)
    norm = np.linalg.norm(aggregated)
    if norm > 0:
        aggregated = aggregated / norm
    
    return aggregated.astype(np.float16)
