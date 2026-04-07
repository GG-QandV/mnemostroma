# SPDX-License-Identifier: FSL-1.1-MIT
"""Deterministic filter — language-agnostic first, keyword fallback second.

Importance is derived in priority order:
  1. Structural precision patterns (numbers+units, versions, errors, links) — any language
  2. NER entities count (handled in pipeline after filter, but flag needs_ner here)
  3. Principle signals — multilingual keyword list
  4. Critical/Important keyword signals — multilingual keyword list
  5. Default: background
"""
import re
from typing import Dict, List, Tuple, Any, Optional

# ── Structural / language-agnostic precision patterns ───────────────────────
PRECISION_PATTERNS = {
    "link":    r"https?://[^\s]+",
    "email":   r"[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}",
    "phone":   r"\+?\d[\d\s\-\(\)]{7,}",
    "number":  r"\d+[.,]?\d*\s*(?:MB|GB|KB|TB|ms|µs|ns|s\b|%|руб|rub|\$|€|EUR|USD|RUB)",
    "version": r"\bv?\d+\.\d+(?:\.\d+)?(?:-[a-z0-9]+)?\b",
    "error":   r"\b(?:error|exception|traceback|errno|assert(?:ion)?|fail(?:ed|ure)?)\b",
    "hash":    r"\b[0-9a-f]{7,40}\b",  # git hashes, IDs
}

# ── Multilingual critical signals ────────────────────────────────────────────
CRITICAL = [
    # RU
    "решил", "выбрал", "запрет", "нельзя", "блокер", "итог", "финально", "критич",
    "отказались", "зафиксировали",
    # EN
    "decided", "chosen", "forbidden", "must not", "blocker", "final", "critical",
    "rejected", "locked in", "resolved",
]

IMPORTANT = [
    # RU
    "важно", "артефакт", "используем", "требование", "зависимость", "нужно",
    "необходимо", "обязательно", "ключевой", "главное",
    # EN
    "important", "artifact", "we use", "requirement", "dependency", "needed",
    "necessary", "mandatory", "key", "essential", "must",
]

CONFLICT = [
    # RU
    "но ", "однако", "противоречит", "изменили", "отменили", "вместо", "пересмотрели",
    "конфликт", "расходится",
    # EN
    "but ", "however", "contradicts", "changed", "cancelled", "instead", "revised",
    "conflict", "diverges", "overrides",
]

# ── Principle signals ─────────────────────────────────────────────────────────
PRINCIPLE_SIGNALS = [
    # RU
    "никогда", "всегда", "запомни это", "это принцип", "правило проекта",
    "архитектурное решение", "это правило", "архитектурный принцип",
    # EN
    "never", "always", "remember this", "non-negotiable", "project rule",
    "architectural principle", "this is a rule", "hard rule",
]

# ── Urgency signals ───────────────────────────────────────────────────────────
URGENCY_SIGNALS = {
    "deadline_h": [
        # RU
        "через час", "через два часа", "в течение часа", "срочно сейчас",
        # EN
        "in 1 hour", "in 2 hours", "within an hour", "asap", "right now",
    ],
    "deadline_d": [
        # RU
        "сегодня", "завтра", "до конца дня", "дедлайн сегодня",
        # EN
        "today", "tomorrow", "by eod", "deadline today", "by end of day",
    ],
    "deadline_w": [
        # RU
        "на этой неделе", "до конца недели", "до пятницы", "через неделю",
        # EN
        "this week", "by friday", "in a week", "end of week", "by eow",
    ],
}

# ── Deadline date pattern ─────────────────────────────────────────────────────
DEADLINE_PATTERN = re.compile(
    r'(?<![v\d.])(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?)'  # date, not version
    r'|(\d{4}-\d{2}-\d{2})'                               # ISO date
    r'|((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2})\b',
    re.IGNORECASE
)

# ── Structural importance: text has code/technical content ────────────────────
_CODE_PATTERN = re.compile(
    r'(?:'
    r'def \w+\s*\('         # Python function
    r'|class \w+[\s(:]'     # class definition
    r'|import \w+'          # import statement
    r'|```'                 # code fence
    r'|`[^`]+`'             # inline code
    r'|\w+\.\w+\(\)'        # method call
    r')',
    re.MULTILINE
)


def _has_structural_importance(text: str, precision_items: list) -> bool:
    """True if text contains language-agnostic signals of importance."""
    if precision_items:
        return True
    if _CODE_PATTERN.search(text):
        return True
    # Long structured text (likely technical context, not idle chat)
    if len(text) > 300:
        return True
    return False


def parse_deadline(text: str, level: str) -> Optional[int]:
    import time
    now = int(time.time())
    if level == "deadline_h":
        return now + 3600
    if level == "deadline_d":
        return now + 86400
    if level == "deadline_w":
        return now + 604800
    m = DEADLINE_PATTERN.search(text)
    if m:
        return now + 86400
    return None


def detect_urgency(text: str) -> Tuple[str, Optional[int]]:
    t = text.lower()
    for level in ("deadline_h", "deadline_d", "deadline_w"):
        if any(sig in t for sig in URGENCY_SIGNALS[level]):
            return level, parse_deadline(text, level)
    m = DEADLINE_PATTERN.search(text)
    if m:
        return "deadline_d", parse_deadline(text, "deadline_d")
    return "none", None


def detect_principle(text: str) -> bool:
    t = text.lower()
    return any(sig in t for sig in PRINCIPLE_SIGNALS)


def deterministic_filter(text: str) -> Dict[str, Any]:
    """Classify text. Language-agnostic structural signals take priority.

    Returns:
        Dict with keys: importance, conflict, precision_items, needs_ner,
                        urgency, deadline_val.
    """
    t = text.lower()

    # 1. Collect structural precision items (language-agnostic)
    precision_items = []
    for ptype, pat in PRECISION_PATTERNS.items():
        for m in re.findall(pat, text, re.IGNORECASE):
            precision_items.append({"type": ptype, "value": m})

    # 2. Principle check (multilingual)
    if detect_principle(text):
        importance = "principle"
    # 3. Critical keywords (multilingual)
    elif any(w in t for w in CRITICAL):
        importance = "critical"
    # 4. Important keywords (multilingual)
    elif any(w in t for w in IMPORTANT):
        importance = "important"
    # 5. Structural signals — no keyword match but has precision/code/length
    elif _has_structural_importance(text, precision_items):
        importance = "important"
    else:
        importance = "background"

    conflict = any(w in t for w in CONFLICT)
    urgency, deadline_val = detect_urgency(text)

    # NER needed unless we already have strong structural signal
    needs_ner = importance not in ("critical", "principle") or not precision_items

    return {
        "importance": importance,
        "conflict": conflict,
        "precision_items": precision_items,
        "needs_ner": needs_ner,
        "urgency": urgency,
        "deadline_val": deadline_val,
    }
