# SPDX-License-Identifier: FSL-1.1-MIT
"""Text compression and tagging utilities for Mnemostroma Observer."""
import logging
from typing import Dict, Any, List, Set, Tuple

logger = logging.getLogger("mnemostroma.observer.utils")


def compress_text(text: str, entities: List[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """Compress text into brief (50 chars) and tags from NER entities.

    Args:
        text: Input text fragment.
        entities: Optional entities from NER (HybridNER output).

    Returns:
        (brief, tags) — tags prefixed by type, deduplicated, max 10.
    """
    # Brief: first 50 chars of the first sentence
    sentences = text.split('.', 1)
    first_sentence = sentences[0].strip() if sentences else text.strip()
    if len(first_sentence) <= 50:
        brief = first_sentence
    else:
        cut = first_sentence[:50].rfind(' ')
        brief = first_sentence[:cut] if cut > 20 else first_sentence[:50]

    # Tags from entities
    tags: List[str] = []
    if entities:
        # Type prefix mapping (HybridNER types → short prefix)
        PREFIX_MAP = {
            "person": "per",
            "organization": "org",
            "address": "loc",
            "date": "date",
            "technology": "tech",
            "decision": "decision",
            "prohibition": "ban",
        }

        seen: Set[str] = set()
        # Sort by score desc — best entities first
        sorted_ents = sorted(entities, key=lambda e: e.get("score", 0), reverse=True)

        for e in sorted_ents:
            value = e.get("value", "").strip()
            if not value:
                continue

            # Normalize: lowercase for dedup check, but keep original case in tag
            dedup_key = value.lower()
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            # Score threshold: 0.5 (matches HybridNER default)
            score = e.get("score", 0)
            if score < 0.5:
                continue

            # Build prefixed tag
            etype = e.get("type", "")
            prefix = PREFIX_MAP.get(etype, "")
            tag = f"{prefix}:{value}" if prefix else value
            tags.append(tag)

            if len(tags) >= 10:
                break

    return brief, tags
