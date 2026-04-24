# SPDX-License-Identifier: FSL-1.1-MIT
"""Memory Model v2 — marker() replaces deterministic_filter().

Instead of "discard or keep", marker() answers "what exactly to save".
Returns: Entity | Emotion | Atmosphere | discard

Basis: docs/MEMORY_SPEC_v2.md §§ 2–5, 9
"""
from __future__ import annotations

import re
import logging
from typing import TYPE_CHECKING, List, Optional

import numpy as np

from .entities import (
    Entity, EntityType, SourceType, ResultType,
    Emotion, EmotionCharge,
    Atmosphere,
    TemporalMarker, TemporalRelations,
    TimeRef, Explicitness,
    MarkerResult, MarkerAction,
)

if TYPE_CHECKING:
    from ..core import SystemContext

logger = logging.getLogger("mnemostroma.marker")

# ---------------------------------------------------------------------------
# Anchor texts (language-agnostic — e5-small works across RU/EN/UA/DE/ZH)
# Key is EntityType member or special string "principle"/"urgency"/"emotion"
# ---------------------------------------------------------------------------

ANCHORS: dict[str, str] = {
    EntityType.DECISION.value: "critical decision chosen selected rejected forbidden",
    EntityType.FACT.value:     "important fact requirement dependency we use",
    EntityType.CODE.value:     "code function class implementation artifact",
    EntityType.EVENT.value:    "event happened occurred completed failed",
    EntityType.QUESTION.value: "question unclear need to check unknown",
    EntityType.RESULT.value:   "result outcome success failure done finished",
    "principle":               "never always rule non-negotiable architectural principle",
    "urgency":                 "deadline urgent today tomorrow asap by end of day",
    "emotion":                 "great terrible wrong not working finally works",
}


# ---------------------------------------------------------------------------
# Temporal keyword sets  (RU + EN + UA basics)
# ---------------------------------------------------------------------------

_PAST_PATTERNS = re.compile(
    r"\b(was|were|had|been|before|yesterday|previously|earlier|already|used to"
    r"|было|были|был|раньше|вчера|ранее|уже|прежде|до этого"
    r"|було|вже|раніше)\b",
    re.IGNORECASE,
)

_FUTURE_PATTERNS = re.compile(
    r"\b(will|shall|going to|tomorrow|next week|soon|later|planned|plan to"
    r"|будет|будем|будут|завтра|потом|следующий|планируем|планируется|скоро"
    r"|буде|завтра|далі)\b",
    re.IGNORECASE,
)

# Emotion charge: positive / negative signals
_POSITIVE_WORDS = re.compile(
    r"\b(great|works|finally|done|success|fixed|perfect|excellent|awesome"
    r"|отлично|работает|готово|успешно|исправлено|хорошо|завершено|наконец)\b",
    re.IGNORECASE,
)

_NEGATIVE_WORDS = re.compile(
    r"\b(terrible|wrong|broken|failed|error|not working|crash|bug|issue|problem"
    r"|ужасно|плохо|сломалось|не работает|ошибка|упало|баг|проблема|не работает)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Temporal inference  (spec § 4)
# ---------------------------------------------------------------------------

def infer_temporal(text: str, chain: List[Entity]) -> TemporalMarker:
    """Infer time reference from text and conversation chain position.

    Language-agnostic: grammar rules vary, chain position is universal.
    Russian present tense often means evaluation of the past — chain context decides.
    """
    # 1. Explicit markers
    if _PAST_PATTERNS.search(text):
        return TemporalMarker(TimeRef.PAST, TimeRef.PAST, Explicitness.EXPLICIT, 1.0)
    if _FUTURE_PATTERNS.search(text):
        return TemporalMarker(TimeRef.FUTURE, TimeRef.FUTURE, Explicitness.EXPLICIT, 1.0)

    # 2. Position in chain (context overrides grammar)
    if chain:
        # After an existing entity → almost always evaluation of past
        return TemporalMarker(TimeRef.PRESENT, TimeRef.PAST, Explicitness.INFERRED, 0.8)

    if _pending_entity_expected(chain):
        return TemporalMarker(TimeRef.PRESENT, TimeRef.FUTURE, Explicitness.INFERRED, 0.6)

    # 3. Unknown
    return TemporalMarker(TimeRef.UNKNOWN, TimeRef.UNKNOWN, Explicitness.LOST, 0.3)


def _pending_entity_expected(chain: List[Entity]) -> bool:
    """True if chain has pending emotions or atmospheres — entity is expected ahead."""
    # Placeholder: can be extended when pending state is tracked in ctx
    return False


def _build_t_rel(temp: TemporalMarker, chain: List[Entity]) -> TemporalRelations:
    """Infer TemporalRelations from temporal marker and chain position (spec § 5.1).

    Rules:
    - INFERRED + ref_time=PAST + chain non-empty  → after=[chain[-1].id]
    - EXPLICIT + gram_time=PAST + chain non-empty  → after=[chain[-1].id]
    - EXPLICIT + gram_time=FUTURE                  → before=[chain[-1].id] if chain
    - Otherwise                                    → empty
    """
    if not chain:
        return TemporalRelations()

    last_id = chain[-1].id

    if temp.explicitness == Explicitness.INFERRED and temp.ref_time == TimeRef.PAST:
        return TemporalRelations(after=[last_id])

    if temp.explicitness == Explicitness.EXPLICIT:
        if temp.gram_time == TimeRef.PAST:
            return TemporalRelations(after=[last_id])
        if temp.gram_time == TimeRef.FUTURE:
            return TemporalRelations(before=[last_id])

    return TemporalRelations()


# ---------------------------------------------------------------------------
# Emotion binding  (spec § 5)
# ---------------------------------------------------------------------------

def bind_emotion(emotion: Emotion, chain: List[Entity]) -> Emotion:
    """Attach emotion to the most recent entity in chain (agent → user → tool).

    If no entity found, mark as pending (will be resolved when next entity appears).
    """
    for source in (SourceType.AGENT, SourceType.USER, SourceType.TOOL):
        candidates = [e for e in reversed(chain) if e.source == source]
        if candidates:
            emotion.ref_entity_id = candidates[0].id
            emotion.ref_source = source
            emotion.pending = False
            return emotion

    emotion.pending = True
    return emotion


def resolve_pending_emotions(new_entity: Entity, pending: List[Emotion]) -> None:
    """Bind all pending emotions to the newly appeared entity (spec § 5).

    Mutates each Emotion in-place; caller should clear the pending list afterward.
    """
    for emotion in pending:
        emotion.ref_entity_id = new_entity.id
        emotion.ref_source = new_entity.source
        emotion.pending = False


# ---------------------------------------------------------------------------
# Anchor vector helpers
# ---------------------------------------------------------------------------

def _get_anchor_vectors(ctx: "SystemContext") -> dict[str, np.ndarray]:
    """Return anchor vectors from ctx (pre-warmed at bootstrap by conductor)."""
    return getattr(ctx, 'anchor_vectors', {})


def _classify(embedding: np.ndarray, anchor_vecs: dict[str, np.ndarray]) -> tuple[str, float]:
    """Return (anchor_label, confidence) via argmax cosine similarity."""
    if not anchor_vecs:
        return EntityType.FACT.value, 0.0

    vec = np.array(embedding, dtype=np.float32).flatten()
    norm = np.linalg.norm(vec)
    if norm > 1e-9:
        vec = vec / norm

    best_label = EntityType.FACT.value
    best_sim = -2.0
    for label, anchor_vec in anchor_vecs.items():
        sim = float(np.dot(vec, anchor_vec))
        if sim > best_sim:
            best_sim = sim
            best_label = label

    return best_label, max(0.0, best_sim)


def _detect_emotion_charge(text: str) -> tuple[EmotionCharge, float]:
    """Keyword-based emotion charge detection, returns (charge, intensity)."""
    pos_count = len(_POSITIVE_WORDS.findall(text))
    neg_count = len(_NEGATIVE_WORDS.findall(text))

    if pos_count > neg_count:
        intensity = min(1.0, 0.4 + pos_count * 0.2)
        return EmotionCharge.POSITIVE, intensity
    if neg_count > pos_count:
        intensity = min(1.0, 0.4 + neg_count * 0.2)
        return EmotionCharge.NEGATIVE, intensity
    if pos_count == neg_count and pos_count > 0:
        return EmotionCharge.UNCERTAIN, 0.5

    return EmotionCharge.NEUTRAL, 0.2


# ---------------------------------------------------------------------------
# Structural prefilter (sync, <1ms)
# ---------------------------------------------------------------------------

def structural_prefilter(text: str) -> bool:
    """Return True if text has enough structure for semantic analysis.

    Rejects: pure whitespace / punctuation, very short fragments with no words.
    """
    stripped = text.strip()
    if len(stripped) < 5:
        return False
    # Must contain at least one word (sequence of word chars)
    return bool(re.search(r"\w{2,}", stripped))


# ---------------------------------------------------------------------------
# Main marker() function  (spec § 9)
# ---------------------------------------------------------------------------

async def marker(
    text: str,
    role: SourceType,
    session_id: str,
    ctx: "SystemContext",
    chain: Optional[List[Entity]] = None,
    pending_emotions: Optional[List[Emotion]] = None,
    embedding: Optional[np.ndarray] = None,
) -> MarkerResult:
    """Replace deterministic_filter: marks what to save rather than discarding.

    Args:
        text:            Raw input text.
        role:            Who produced the text (user / agent / tool).
        session_id:      Current session identifier.
        ctx:             SystemContext with models and config.
        chain:           Recent Entity objects from this session (for temporal inference).
        pending_emotions: Pending emotions waiting for an entity to bind to.

    Returns:
        MarkerResult with action and the created object (or discard).
    """
    chain = chain or []
    pending_emotions = pending_emotions or []

    # ── Hard discard ──────────────────────────────────────────────────────
    stripped = text.strip()
    if len(stripped) < 5:
        return MarkerResult.discard()

    # Anchor Stoplist (v1.8.4 guard) — prevent noisy/parasitic phrases
    stoplist = getattr(ctx.config.observer, 'anchor_stoplist', [])
    if any(stop_phrase.lower() in stripped.lower() for stop_phrase in stoplist):
        logger.debug(f"marker: discarding text in stoplist: {stripped[:50]}...")
        return MarkerResult.discard()

    # ── User path: structural only, nearly always creates an Entity ───────
    if role == SourceType.USER:
        temp = infer_temporal(text, chain)
        entity = Entity.create(
            what=stripped,
            entity_type=EntityType.FACT,
            source=SourceType.USER,
            temp=temp,
            importance=0.7,  # USER_INTENT default
            t_rel=_build_t_rel(temp, chain),
        )
        if pending_emotions:
            resolve_pending_emotions(entity, pending_emotions)
        return MarkerResult(
            action=MarkerAction.CREATE_ENTITY,
            entity=entity,
            confidence=1.0,
        )

    # ── Agent / tool path: structural prefilter + semantic classification ──
    if not structural_prefilter(stripped):
        # Atmosphere: text has time signal but no entity content
        temp = infer_temporal(text, chain)
        if temp.explicitness != Explicitness.LOST:
            atm = Atmosphere.create(
                signals=stripped.split()[:10],
                noise_level=0.8,
            )
            return MarkerResult(
                action=MarkerAction.CREATE_ATMOSPHERE,
                atmosphere=atm,
                confidence=0.5,
            )
        return MarkerResult.discard()

    # ── Encode text (skip if pre-computed by pipeline) ────────────────────
    if embedding is not None:
        embedding = np.array(embedding, dtype=np.float32).flatten()
    elif ctx.models and ctx.models.embedder:
        try:
            raw = await ctx.models.embedder.aencode(stripped)
            embedding = np.array(raw, dtype=np.float32).flatten()
        except Exception as e:
            logger.warning(f"marker: encode failed: {e}")

    # ── Classify against anchor vectors (pre-warmed in ctx at bootstrap) ──
    anchor_vecs = _get_anchor_vectors(ctx)
    if embedding is not None and anchor_vecs:
        top_label, confidence = _classify(embedding, anchor_vecs)
    else:
        # Fallback: keyword heuristic if no embedder
        top_label = _keyword_classify(text)
        confidence = 0.5

    # ── Decide: Entity / Emotion / Atmosphere based on top anchor ──────────
    temp = infer_temporal(text, chain)

    if top_label == "emotion":
        charge, intensity = _detect_emotion_charge(text)
        emotion = Emotion.create(
            charge=charge,
            intensity=intensity,
            pending=True,
        )
        emotion = bind_emotion(emotion, chain)
        if pending_emotions is not None:
            pass  # caller manages the pending list
        return MarkerResult(
            action=MarkerAction.CREATE_EMOTION,
            emotion=emotion,
            confidence=confidence,
        )

    # Map special labels to entity types
    entity_type = _label_to_entity_type(top_label)

    entity = Entity.create(
        what=stripped,
        entity_type=entity_type,
        source=role,
        temp=temp,
        importance=_importance_from_label(top_label),
        embedding=embedding,
        t_rel=_build_t_rel(temp, chain),
    )

    if pending_emotions:
        resolve_pending_emotions(entity, pending_emotions)

    return MarkerResult(
        action=MarkerAction.CREATE_ENTITY,
        entity=entity,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _label_to_entity_type(label: str) -> EntityType:
    """Map anchor label to EntityType, handling special labels."""
    try:
        return EntityType(label)
    except ValueError:
        pass
    if label == "principle":
        return EntityType.DECISION
    if label == "urgency":
        return EntityType.EVENT
    return EntityType.FACT


def _importance_from_label(label: str) -> float:
    """Default importance score by anchor label."""
    return {
        EntityType.DECISION.value: 0.9,
        "principle":               1.0,
        "urgency":                 0.85,
        EntityType.FACT.value:     0.6,
        EntityType.CODE.value:     0.7,
        EntityType.EVENT.value:    0.65,
        EntityType.QUESTION.value: 0.5,
        EntityType.RESULT.value:   0.75,
    }.get(label, 0.5)


# Lightweight keyword classifier — used when embedder is unavailable
_KEYWORD_MAP = [
    (EntityType.DECISION.value, re.compile(
        r"\b(decided|chosen|rejected|forbidden|решили|выбрали|отказались)\b", re.I)),
    (EntityType.CODE.value, re.compile(
        r"\b(def |class |function|import |async |return |код|функция|класс)\b", re.I)),
    (EntityType.QUESTION.value, re.compile(
        r"[?？]|\\b(why|how|what|when|where|почему|как|что|когда|где)\\b", re.I)),
    (EntityType.RESULT.value, re.compile(
        r"\b(done|complete|finished|failed|готово|завершено|выполнено|упало)\b", re.I)),
    ("emotion", re.compile(
        r"\b(great|terrible|wrong|works|finally|отлично|ужасно|наконец)\b", re.I)),
]


def _keyword_classify(text: str) -> str:
    for label, pattern in _KEYWORD_MAP:
        if pattern.search(text):
            return label
    return EntityType.FACT.value
