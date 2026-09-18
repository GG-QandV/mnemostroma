# SPDX-License-Identifier: FSL-1.1-MIT
"""Text compression and tagging utilities for Mnemostroma Observer."""
import logging
import re
from typing import Any

logger = logging.getLogger("mnemostroma.observer.utils")

# Целевая длина связного brief: короткий фрагмент дополняется следующими
# предложениями до этого минимума (если текст позволяет).
_BRIEF_MIN_LEN = 50
# Жёсткий потолок длины brief — обрезка идёт только по границе слова.
_BRIEF_MAX_LEN = 120
# Фрагмент короче этого порога сам по себе неинформативен (обрывок слова,
# служебные символы) — к нему добавляются последующие предложения.
_BRIEF_EXTEND_FLOOR = 30
# Минимальная длина brief, при которой он считается связным (для инжекта).
_BRIEF_QUALITY_MIN_LEN = 20

# Сокращения, точку в которых нельзя принимать за границу предложения.
_SENTENCE_PROTECT = ("т.е.", "т.д.", "т.п.", "и.т.д.", "и.т.п.", "г.")
# Символы, которыми завершается предложение и которые срезаются с конца brief.
_SENTENCE_END = ".,;!?…:—"


def _split_sentences(text: str) -> list[str]:
    """Делит текст на предложения без ложных разрывов.

    Точки внутри десятичных дробей, многоточий и распространённых сокращений
    защищаются от разбиения (наивный ``split('.', 1)`` был источником мусорных
    обрывков в brief — см. ТЗ про garbage briefs).
    """
    protected = re.sub(r"\b(\d+)\.(\d+)\b", r"\1<PRT_DOT>\2", text)
    protected = protected.replace("...", "<PRT_ELLIP>").replace("…", "<PRT_ELLIP>")
    for abbr in _SENTENCE_PROTECT:
        protected = protected.replace(abbr, abbr.replace(".", "<PRT_DOT>"))
    raw_parts = re.split(r"(?<=[.!?])\s+|\n+", protected)
    sentences: list[str] = []
    for part in raw_parts:
        part = part.strip()
        if not part:
            continue
        sentences.append(part.replace("<PRT_DOT>", ".").replace("<PRT_ELLIP>", "..."))
    return sentences


def _truncate_words(text: str, max_len: int) -> str:
    """Обрезает текст до max_len по границе слова (не рвёт слово посреди)."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len].rfind(" ")
    if cut > max_len // 2:
        return text[:cut].rstrip(_SENTENCE_END).strip()
    return text[:max_len].strip()


def _build_brief(sentences: list[str]) -> str:
    """Собирает связный brief из предложений, без обрывков слов.

    Используется первое осмысленное предложение. Если оно короче
    ``_BRIEF_EXTEND_FLOOR`` символов — дополняется следующими предложениями до
    ``_BRIEF_MIN_LEN``, но не длиннее ``_BRIEF_MAX_LEN``.
    """
    if not sentences:
        return ""
    first = sentences[0].rstrip(_SENTENCE_END).strip()
    if not first:
        return ""
    if len(first) > _BRIEF_MAX_LEN:
        return _truncate_words(first, _BRIEF_MAX_LEN)
    if len(first) >= _BRIEF_EXTEND_FLOOR:
        return first

    # Первое предложение короткое — дополняем следующими.
    acc = first
    for s in sentences[1:]:
        s = s.rstrip(_SENTENCE_END).strip()
        if not s:
            continue
        candidate = f"{acc} {s}" if acc else s
        if len(candidate) > _BRIEF_MAX_LEN:
            room = _BRIEF_MAX_LEN - len(acc)
            if room > 0:
                acc = f"{acc} {_truncate_words(s, room)}".rstrip()
            break
        acc = candidate
        if len(acc) >= _BRIEF_MIN_LEN:
            break
    return acc


def _extract_tags(entities: list[dict[str, Any]]) -> list[str]:
    """Строит теги из NER-сущностей: префикс типа, дедуп, порог, максимум 10."""
    tags: list[str] = []
    if not entities:
        return tags

    # Type prefix mapping (HybridNER types → short prefix)
    PREFIX_MAP = {
        "person": "per",
        "человек": "per",
        "organization": "org",
        "организация": "org",
        "address": "loc",
        "адрес": "loc",
        "date": "date",
        "дата": "date",
        "technology": "tech",
        "технология": "tech",
        "decision": "decision",
        "решение": "decision",
        "prohibition": "ban",
        "запрет": "ban",
    }

    seen: set[str] = set()
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

    return tags


def compress_text(text: str, entities: list[dict[str, Any]] = None) -> tuple[str, list[str]]:
    """Compress text into brief (50-120 chars) and tags from NER entities.

    Вместо наивной обрезки первых 50 символов (которая рвала слова посреди и
    давала мусорные обрывки типа ``"сс пор завер"``) собирается первое
    осмысленное предложение. Точки в JSON/дробях/сокращениях не считаются
    границей предложения.

    Args:
        text: Input text fragment.
        entities: Optional entities from NER (HybridNER output).

    Returns:
        (brief, tags) — tags prefixed by type, deduplicated, max 10.
    """
    normalized = re.sub(r"\s+", " ", text or "").strip()
    if not normalized:
        return "", _extract_tags(entities)

    brief = _build_brief(_split_sentences(normalized))
    tags = _extract_tags(entities)
    return brief, tags


def is_quality_brief(brief: str) -> bool:
    """Проверка связности brief перед попаданием в инжект.

    Отсекает заведомо обрубленные/мусорные краткие описания: слишком короткие,
    без букв или с преобладанием служебных символов. Используется
    ``integration/proxy.py`` при сборке ``<memory_context>``.
    """
    b = (brief or "").strip()
    if len(b) < _BRIEF_QUALITY_MIN_LEN:
        return False
    alpha = sum(ch.isalpha() for ch in b)
    if alpha == 0:
        return False
    return alpha / len(b) >= 0.5
