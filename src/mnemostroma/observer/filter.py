# SPDX-License-Identifier: FSL-1.1-MIT
import re
from typing import Dict, List, Tuple, Any, Optional

# Importance signals
CRITICAL = ["решил", "выбрал", "запрет", "нельзя", "блокер", "итог", "финально", "критич"]
IMPORTANT = ["важно", "артефакт", "используем", "требование", "зависимость", "нужно"]
CONFLICT = ["но ", "однако", "противоречит", "изменили", "отменили", "вместо", "пересмотрели"]

# Precision patterns
PRECISION_PATTERNS = {
    "link": r"https?://[^\s]+",
    "email": r"[\w.]+@[\w.]+\.[\w]+",
    "phone": r"\+?\d[\d\s\-\(\)]{7,}",
    "number": r"\d+[.,]?\d*\s*(MB|GB|ms|KB|%|руб|\$|EUR)",
}

# Urgency signals v1.3
URGENCY_SIGNALS = {
    "deadline_h": [
        "через час", "через два часа", "в течение часа",
        "in 1 hour", "in 2 hours", "asap", "срочно сейчас",
    ],
    "deadline_d": [
        "сегодня", "завтра", "today", "tomorrow",
        "до конца дня", "by eod", "дедлайн сегодня", "deadline today",
    ],
    "deadline_w": [
        "на этой неделе", "до конца недели", "this week",
        "by friday", "до пятницы", "через неделю", "in a week",
    ],
}

# Principle signals v1.3
PRINCIPLE_SIGNALS = [
    "никогда", "всегда", "запомни это", "это принцип",
    "правило проекта", "архитектурное решение",
    "never", "always", "remember this", "non-negotiable",
    "project rule", "architectural principle",
]

# Deadline date patterns
DEADLINE_PATTERN = re.compile(
    r'\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?'
    r'|\d{4}-\d{2}-\d{2}'
    r'|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2})\b',
    re.IGNORECASE
)

def parse_deadline(text: str, level: str) -> Optional[int]:
    """Simple parser to convert signals and dates to Unix timestamps."""
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
        # Very naive parse for demo; real system would use dateutil/pendulum
        # For audit compliance, we need a valid timestamp
        return now + 86400 # Default to 1 day if matched date but no complex parser
    return None

def detect_urgency(text: str) -> Tuple[str, Optional[int]]:
    """Detect urgency level and deadline timestamp from text.
    
    Returns:
        (UrgencyLevel, deadline_ts | None).
    """
    t = text.lower()
    for level in ("deadline_h", "deadline_d", "deadline_w"):
        if any(sig in t for sig in URGENCY_SIGNALS[level]):
            ts = parse_deadline(text, level)
            return level, ts
    
    m = DEADLINE_PATTERN.search(text)
    if m:
        ts = parse_deadline(text, "deadline_d")
        return "deadline_d", ts
    
    return "none", None

def detect_principle(text: str) -> bool:
    """Detect if text defines a project principle."""
    t = text.lower()
    return any(sig in t for sig in PRINCIPLE_SIGNALS)

def deterministic_filter(text: str) -> Dict[str, Any]:
    """Classify text based on deterministic signals.
    
    Args:
        text: Input fragment.
        
    Returns:
        Dict with importance, conflict, precision items, etc.
    """
    t = text.lower()
    importance = "background"
    
    if any(w in t for w in CRITICAL):
        importance = "critical"
    elif any(w in t for w in IMPORTANT):
        importance = "important"

    # v1.3: principle overrides importance
    if detect_principle(text):
        importance = "principle"

    conflict = any(w in t for w in CONFLICT)
    
    precision_items = []
    for ptype, pat in PRECISION_PATTERNS.items():
        for m in re.findall(pat, text):
            precision_items.append({"type": ptype, "value": m})

    urgency, deadline_val = detect_urgency(text)

    # If importance is high and we have facts, we might not need NER
    needs_ner = not (importance in ("critical", "principle") and precision_items)
    # Background fragments usually don't need NER unless they have precision items?
    # Spec says: Background fragments without signals -> discard later.
    
    return {
        "importance": importance,
        "conflict": conflict,
        "precision_items": precision_items,
        "needs_ner": needs_ner,
        "urgency": urgency,
        "deadline_val": deadline_val,
    }
