# SPDX-License-Identifier: FSL-1.1-MIT
"""Hybrid NER: DistilBERT + regex patterns for robust entity extraction."""
import re
import logging
import asyncio
from typing import List, Dict, Any
from .bert_ner import BertNER

logger = logging.getLogger(__name__)

ENTITY_PRIORITY = {
    "decision": 1, "prohibition": 1,      # критичные
    "outcome": 1,                         # from recent commit
    "technology": 2,                      # важные
    "PER": 3, "ORG": 3, "LOC": 3,         # справочники
    "DATE": 4, "MONEY": 4,                # факты
}

# Technology names (language-independent)
TECH_PATTERN = re.compile(
    r'\b(Python|Rust|Go|Java|JavaScript|TypeScript|C\+\+|Ruby|PHP|Swift|Kotlin|'
    r'PostgreSQL|MySQL|MongoDB|Redis|SQLite|Cassandra|ClickHouse|'
    r'Docker|Kubernetes|Nginx|Apache|Linux|Windows|'
    r'React|Vue|Angular|FastAPI|Django|Flask|Spring|'
    r'ONNX|TensorFlow|PyTorch|LangChain|'
    r'Git|GitHub|GitLab|Jira|Slack|Telegram|'
    r'AWS|GCP|Azure|Vercel|Heroku)\b',
    re.IGNORECASE
)

OUTCOME_PATTERNS = [
    # RU: success/failure outcomes (captures standalone or with context)
    re.compile(r'\b(?:успешно|успешным|успешен|работает|заработал|сработало|помогло|решило)\b(?:\s+[а-яё]{1,30})?', re.IGNORECASE),  # success (flexible)
    re.compile(r'\b(?:не сработало|провал|неудачно|ошибка|крах|потерпел неудачу|не помогло)\b(?:\s+[а-яё]{1,30})?', re.IGNORECASE),  # failure (flexible)
    # EN: success/failure (flexible)
    re.compile(r'\b(?:successfully|works|worked|fixed|solved)\b(?:\s+[a-z]{1,30})?', re.IGNORECASE),  # success
    re.compile(r'\b(?:failed|broken|crashes|doesn\'t work)\b(?:\s+[a-z]{1,30})?', re.IGNORECASE),  # failure
]

DECISION_PATTERNS = [
    # RU
    re.compile(r'(?:решили|решил|решено|выбрали|выбрал|будем использовать|переходим на|'
               r'принято решение|приняли решение|приняли|договорились|утвердили|одобрили)[:\s]+(.{3,60}?)(?=[.,;!\n]|$)', re.IGNORECASE),
    # EN
    re.compile(r'(?:decided to|chose|will use|switching to|agreed on|approved|'
               r'going with|selected|picked)[:\s]+(.{3,60}?)(?=[.,;!\n]|$)', re.IGNORECASE),
    # UA
    re.compile(r'(?:вирішили|вирішив|обрали|будемо використовувати|переходимо на|'
               r'затвердили|домовились)[:\s]+(.{3,60}?)(?=[.,;!\n]|$)', re.IGNORECASE),
]

PROHIBITION_PATTERNS = [
    # RU
    re.compile(r'(?:запрещено|нельзя|не использовать|отказались от|убрали|'
               r'не применять|исключить|заблокировать|никакого|никакой|'
               r'исключён|исключена|без внешних)[:\s]+(.{3,60}?)(?=[.,;!\n]|$)', re.IGNORECASE),
    # EN
    re.compile(r'(?:forbidden|must not|do not use|banned|prohibited|'
               r'deprecated|removed|blocked|no external)[:\s]+(.{3,60}?)(?=[.,;!\n]|$)', re.IGNORECASE),
    # UA
    re.compile(r'(?:заборонено|не можна|не використовувати|відмовились від|'
               r'виключити|заблокувати)[:\s]+(.{3,60}?)(?=[.,;!\n]|$)', re.IGNORECASE),
]


class HybridNER:
    """Combines DistilBERT token classification with regex patterns.

    DistilBERT handles: PER, ORG, LOC, DATE
    Regex handles: technology, decision, prohibition, outcome

    Why: DistilBERT-NER is weak on multilingual subword splits.
    Regex reliably catches structured patterns that models miss.
    Expected latency: <50ms combined.
    """

    def __init__(self, model_path: str, tokenizer_path: str):
        self._bert = BertNER(model_path=model_path, tokenizer_path=tokenizer_path)

    def load(self) -> None:
        """Load ONNX model (lazy by default via BertNER)."""
        self._bert.load()

    async def extract_entities(
        self, text: str, threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Extract entities using both model and regex.

        Args:
            text: Input text (any language).
            threshold: Confidence threshold for model predictions.

        Returns:
            List of entity dicts with type, value, score, start, end.
        """
        entities: List[Dict[str, Any]] = []

        # 1. Model-based NER (PER, ORG, LOC, DATE)
        # Adheres to Rule 2: ONNX inference runs in executor
        try:
            loop = asyncio.get_running_loop()
            model_entities = await loop.run_in_executor(
                None, self._bert.predict_entities, text, threshold
            )
            entities.extend(model_entities)
        except Exception as e:
            logger.error(f"BertNER failed: {e}")

        # 2. Regex: technologies
        for m in TECH_PATTERN.finditer(text):
            if not self._overlaps(entities, m.start(), m.end(), "technology"):
                entities.append({
                    "type": "technology",
                    "value": m.group(0),
                    "score": 1.0,
                    "start": m.start(),
                    "end": m.end()
                })

        # 3. Regex: decisions (HIGH priority - can coexist with technology)
        for pattern in DECISION_PATTERNS:
            for m in pattern.finditer(text):
                val = m.group(1).strip()
                full_start = m.start(1)
                if not self._overlaps(entities, full_start, full_start + len(val), "decision"):
                    entities.append({
                        "type": "decision",
                        "value": val,
                        "score": 0.9,
                        "start": full_start,
                        "end": full_start + len(val)
                    })

        # 4. Regex: prohibitions (HIGH priority - can coexist with technology)
        for pattern in PROHIBITION_PATTERNS:
            for m in pattern.finditer(text):
                val = m.group(1).strip()
                full_start = m.start(1)
                if not self._overlaps(entities, full_start, full_start + len(val), "prohibition"):
                    entities.append({
                        "type": "prohibition",
                        "value": val,
                        "score": 0.9,
                        "start": full_start,
                        "end": full_start + len(val)
                    })

        # 5. Regex: outcomes (HIGH priority - success/failure/in_progress)
        for pattern in OUTCOME_PATTERNS:
            for m in pattern.finditer(text):
                val = m.group(0).strip()
                full_start = m.start()
                if not self._overlaps(entities, full_start, full_start + len(val), "outcome"):
                    entities.append({
                        "type": "outcome",
                        "value": val,
                        "score": 0.85,
                        "start": full_start,
                        "end": full_start + len(val)
                    })

        # Sort by position
        entities.sort(key=lambda e: e["start"])
        return entities

    def _overlaps(self, entities: List[Dict[str, Any]], start: int, end: int, candidate_type: str) -> bool:
        """Check if span overlaps with existing entities considering priority."""
        for e in entities:
            if start < e["end"] and end > e["start"]:
                prio_candidate = ENTITY_PRIORITY.get(candidate_type, 99)
                prio_existing = ENTITY_PRIORITY.get(e.get("type", ""), 99)
                if prio_candidate < prio_existing:
                    # Более высокий приоритет — разрешить сосуществование
                    return False
                return True
        return False

    def close(self) -> None:
        """Release resources."""
        self._bert.close()
