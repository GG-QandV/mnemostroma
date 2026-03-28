# SPDX-License-Identifier: FSL-1.1-MIT
import logging
from typing import Dict, Any, List

logger = logging.getLogger("mnemostroma.observer.utils")

def compress_text(text: str, entities: List[Dict[str, Any]] = None) -> tuple[str, List[str]]:
    """Compress text into brief (50 chars) and tags.
    
    Args:
        text: Input text fragment.
        entities: Optional entities from NER.
        
    Returns:
        (brief, tags)
    """
    # Brief: first 50 chars of the first sentence
    sentences = text.split('.', 1)
    first_sentence = sentences[0].strip() if sentences else text.strip()
    brief = first_sentence[:50]
    
    # Tags: from entities + simple keyword extraction logic
    tags = []
    if entities:
        tags = [e["value"] for e in entities if e["score"] > 0.7]
    
    # Limit tags logic is handled in the pipeline via config
    return brief, tags
