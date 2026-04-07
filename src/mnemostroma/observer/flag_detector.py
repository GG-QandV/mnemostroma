# SPDX-License-Identifier: FSL-1.1-MIT
"""Observer flag detection — fast signal-based flag assignment.

All detectors must complete within 1-2ms total.
No model inference — only regex and dictionary lookups.
"""
import re
import logging
from typing import Dict, Any, List, Optional

logger = logging.getLogger("mnemostroma.observer.flags")


# --- Outcome detection ---
# Outcome signals: what happened with the process/decision

_OUTCOME_SIGNALS: Dict[str, List[re.Pattern]] = {
    "success": [
        re.compile(r, re.IGNORECASE) for r in [
            r"\bуспешно\b", r"\bготово\b", r"\bсделано\b", r"\bработает\b",
            r"\bзавершено\b", r"\bреализовано\b", r"\bвнедрено\b",
            r"\bпройден[оы]?\b", r"\bрешено\b", r"\bисправлено\b",
            r"\bsuccess\b", r"\bdone\b", r"\bfixed\b", r"\bcompleted?\b",
            r"\bworks?\b", r"\bpassed\b", r"\bresolved\b",
            r"\bвсе тесты\s+прош", r"\ball\s+tests?\s+pass",
        ]
    ],
    "failure": [
        re.compile(r, re.IGNORECASE) for r in [
            r"\bне\s+(?:удалось|сработало|получилось|вышло)\b",
            r"\bошибка\b", r"\bпровал\b", r"\bсломал[оиа]?\b",
            r"\bупал[оиа]?\b", r"\bкрашнул\b", r"\bбаг\b",
            r"\bfail(?:ed|ure)?\b", r"\berror\b", r"\bcrash(?:ed)?\b",
            r"\bbroke[n]?\b", r"\bbug\b",
            r"\bне\s+работает\b", r"\bне\s+проходи[тт]\b",
        ]
    ],
    "abandoned": [
        re.compile(r, re.IGNORECASE) for r in [
            r"\bотменили\b", r"\bотказались\b", r"\bзабросили\b",
            r"\bне\s+будем\b", r"\bбольше\s+не\b", r"\bсвернули\b",
            r"\babandoned?\b", r"\bcancell?ed\b", r"\bdropped\b",
            r"\bсняли\s+с\b", r"\bзакрыли\s+без\b",
        ]
    ],
}

def detect_outcome(text: str) -> str:
    """Detect process outcome from text signals.
    
    Returns: success | failure | abandoned | neutral | pending
    
    Priority: failure > abandoned > success > neutral
    If no signals found → pending (not enough info yet)
    """
    scores: Dict[str, int] = {"success": 0, "failure": 0, "abandoned": 0}
    
    for outcome_type, patterns in _OUTCOME_SIGNALS.items():
        for pattern in patterns:
            if pattern.search(text):
                scores[outcome_type] += 1
    
    total = sum(scores.values())
    if total == 0:
        return "pending"
    
    # Failure beats all (negatives are remembered more strongly)
    if scores["failure"] > 0:
        return "failure"
    if scores["abandoned"] > 0:
        return "abandoned"
    if scores["success"] > 0:
        return "success"
    
    return "neutral"


# --- User pin detection ---
# User explicitly asks to remember

_PIN_PATTERNS: List[re.Pattern] = [
    re.compile(r, re.IGNORECASE) for r in [
        r"\bзапомни\b", r"\bне\s+забудь\b", r"\bзафиксируй\b",
        r"\bзапиши\b", r"\bобрати\s+внимание\b",
        r"\bважно\s+(?:на\s+)?будущее\b", r"\bпригодится\b",
        r"\bна\s+перспективу\b", r"\bна\s+будущее\b",
        r"\bremember\b", r"\bdon'?t\s+forget\b", r"\bkeep\s+(?:in\s+)?mind\b",
        r"\bnote\s+(?:this|that)\b", r"\bpin\s+this\b",
        r"\bэто\s+(?:нам\s+)?(?:ещё\s+)?понадобится\b",
    ]
]

def detect_user_pin(text: str) -> bool:
    """Detect if user explicitly asks to remember something."""
    for pattern in _PIN_PATTERNS:
        if pattern.search(text):
            return True
    return False


# Multi-session detection
# Determining that process spans multiple sessions
# At level B.1 — by text signals
# At level B.2 — supplemented by cosine continuation

_MULTI_SESSION_PATTERNS: List[re.Pattern] = [
    re.compile(r, re.IGNORECASE) for r in [
        r"\bпродолж", r"\bкак\s+(?:и\s+)?(?:в\s+)?прошл",
        r"\bв\s+прошлой\s+сесси[ий]\b", r"\bранее\s+(?:мы\s+)?",
        r"\bвчера\s+(?:мы\s+)?", r"\bна\s+прошлой\s+неделе\b",
        r"\bcontinuing\b", r"\bas\s+before\b", r"\bpreviously\b",
        r"\blast\s+session\b", r"\byesterday\b",
        r"\bвозвращаемся\s+к\b", r"\bснова\s+(?:работаем|берёмся)\b",
        r"\bследующий\s+(?:этап|шаг|фаза)\b",
    ]
]

def detect_multi_session(text: str) -> bool:
    """Detect signals that this is part of a multi-session process."""
    for pattern in _MULTI_SESSION_PATTERNS:
        if pattern.search(text):
            return True
    return False


def detect_mention_type(text: str, entities: List[Dict[str, Any]]) -> str:
    """Classify mention type for dominant entity: 'focus' or 'passing'.

    focus:   entity in first 30% of text OR appears more than once
    passing: single mention in second half of text

    Runs in <1ms — string ops only, no model inference.
    """
    if not entities:
        return "focus"  # no NER data — assume topic is the focus

    # Use highest-scored entity as representative
    top = max(entities, key=lambda e: e.get("score", 0))
    value = top.get("value", "").lower().strip()
    if not value:
        return "focus"

    text_lower = text.lower()
    text_len = len(text_lower)
    if text_len == 0:
        return "focus"

    # Count occurrences
    count = text_lower.count(value)
    if count > 1:
        return "focus"

    # Single occurrence — check position
    pos = text_lower.find(value)
    if pos == -1 or pos / text_len < 0.5:
        return "focus"

    return "passing"


def detect_all_flags(text: str, entities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Run all signal-based detectors. <1ms total.

    Returns partial flags dict to merge into anchor flags.
    """
    return {
        "outcome": detect_outcome(text),
        "user_pin": detect_user_pin(text),
        "multi_session": detect_multi_session(text),
        "mention_type": detect_mention_type(text, entities or []),
    }
