# SPDX-License-Identifier: FSL-1.1-MIT
"""Session type classifier for Content Branch routing.

Mechanism #12 from MNEMOSTROMA_INVENTORY.md.
Scores accumulated session text against three keyword sets and returns
argmax. Used by PersistStep to decide whether to route to ContentManager.
"""
from __future__ import annotations

import re
from typing import Optional


# ── Keyword sets (tuned for typical agent session content) ───────────────────

_CONTENT_KEYWORDS: frozenset[str] = frozenset({
    "def ", "class ", "import ", "function", "implementation",
    "async def", "return ", "```python", "```typescript", "```js",
    "```bash", "```sql", "schema", "migration", "refactor",
    "interface ", "type ", "enum ", "struct ",
})

_RESEARCH_KEYWORDS: frozenset[str] = frozenset({
    "analyze", "compare", "article", "research", "study",
    "benchmark", "metric", "evaluate", "hypothesis", "evidence",
    "source", "citation", "review", "findings", "survey",
})

_CONTEXT_KEYWORDS: frozenset[str] = frozenset({
    "discuss", "plan", "task", "blocker", "decision",
    "meeting", "agenda", "status", "update", "next steps",
    "sprint", "milestone", "deadline", "priority", "stakeholder",
})

# Minimum score to classify (below → None / unclassified)
_MIN_SCORE: int = 2


def classify_session_type(text: str) -> Optional[str]:
    """Classify session text into content / research / context category.

    Returns None if no keyword set reaches _MIN_SCORE (unclassified).
    Operates on lowercase text to be case-insensitive.

    Performance: O(n) string scan, <0.1ms for typical session text.

    Args:
        text: Accumulated session text (full turn or stripped form).

    Returns:
        "content" | "research" | "context" | None
    """
    lower = text.lower()

    scores: dict[str, int] = {
        "content": sum(1 for kw in _CONTENT_KEYWORDS if kw in lower),
        "research": sum(1 for kw in _RESEARCH_KEYWORDS if kw in lower),
        "context": sum(1 for kw in _CONTEXT_KEYWORDS if kw in lower),
    }

    best = max(scores, key=lambda k: scores[k])
    if scores[best] < _MIN_SCORE:
        return None
    return best
