# SPDX-License-Identifier: FSL-1.1-MIT
"""Experience Layer — ExperienceCluster and ExperienceIndex.

Accumulates long-term behavioural patterns per tag.
Generates Intuition Signals (DO_THIS / AVOID_THIS / TENSION) for ConductorProxy.
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

logger = logging.getLogger("mnemostroma.experience")

# Score events (spec §3)
SCORE_USE       =  1.0
SCORE_DEEP_USE  =  2.5   # continuation detected
SCORE_CONFLICT  = -1.5
SCORE_IGNORE    = -0.5   # reserved for future feedback signals

def _compute_maturity(session_count: int, thresholds: tuple) -> str:
    """thresholds = (master, expert, practitioner, apprentice)"""
    master, expert, practitioner, apprentice = thresholds
    if session_count > master:       return "master"
    if session_count > expert:       return "expert"
    if session_count > practitioner: return "practitioner"
    if session_count > apprentice:   return "apprentice"
    return "novice"


# Minimum emotion samples before emitting ATTRACT/REPEL signal (spec §5.4)
_EMOTION_MIN_SAMPLES = 3


@dataclass
class ExperienceCluster:
    """Behavioural statistics for a single tag/topic."""
    tag: str
    session_count: int = 0
    score_sum: float = 0.0
    conflict_count: int = 0
    last_updated: int = field(default_factory=lambda: int(time.time()))
    emotion_positive: int = 0
    emotion_negative: int = 0
    emotion_intensity_sum: float = 0.0
    _thresholds: tuple = field(default=(100, 30, 10, 5), repr=False)

    @property
    def maturity(self) -> str:
        return _compute_maturity(self.session_count, self._thresholds)

    @property
    def avg_score(self) -> float:
        if self.session_count == 0:
            return 0.0
        return self.score_sum / self.session_count

    @property
    def conflict_rate(self) -> float:
        if self.session_count == 0:
            return 0.0
        return self.conflict_count / self.session_count

    @property
    def emotion_count(self) -> int:
        return self.emotion_positive + self.emotion_negative

    @property
    def emotion_valence(self) -> float:
        """Normalised valence in [-1, 1]. 0 if no emotion data."""
        total = self.emotion_count
        if total == 0:
            return 0.0
        return (self.emotion_positive - self.emotion_negative) / total

    @property
    def emotion_signal(self) -> Optional[str]:
        """ATTRACT | REPEL | AMBIVALENT | None (insufficient data)."""
        total = self.emotion_count
        if total < _EMOTION_MIN_SAMPLES:
            return None
        v = self.emotion_valence
        if v >= 0.6:
            return "ATTRACT"
        if v <= -0.6:
            return "REPEL"
        if abs(v) <= 0.3 and total >= 6:
            return "AMBIVALENT"
        return None

    def record(self, score_delta: float, is_conflict: bool = False) -> None:
        self.session_count += 1
        self.score_sum += score_delta
        if is_conflict:
            self.conflict_count += 1
        self.last_updated = int(time.time())

    def record_emotion(self, charge: str, intensity: float) -> None:
        """Record one emotion event. charge: 'positive' | 'negative'."""
        if charge == "positive":
            self.emotion_positive += 1
        else:
            self.emotion_negative += 1
        self.emotion_intensity_sum += intensity
        self.last_updated = int(time.time())

    def decay(self, days_inactive: float, rate: float) -> None:
        """Apply forgetting curve: reduce score_sum by rate * days_inactive."""
        reduction = rate * days_inactive
        self.score_sum = max(-abs(self.score_sum), self.score_sum - reduction)
        self.last_updated = int(time.time())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tag": self.tag,
            "session_count": self.session_count,
            "score_sum": round(self.score_sum, 4),
            "conflict_count": self.conflict_count,
            "last_updated": self.last_updated,
            "maturity": self.maturity,
            "avg_score": round(self.avg_score, 4),
            "emotion_positive": self.emotion_positive,
            "emotion_negative": self.emotion_negative,
            "emotion_intensity_sum": round(self.emotion_intensity_sum, 4),
            "emotion_valence": round(self.emotion_valence, 4),
            "emotion_signal": self.emotion_signal,
        }


class ExperienceIndex:
    """In-memory index of ExperienceClusters keyed by tag."""

    def __init__(self, signal_threshold: float = 0.75,
                 maturity_apprentice: int = 5, maturity_practitioner: int = 10,
                 maturity_expert: int = 30, maturity_master: int = 100):
        self._clusters: Dict[str, ExperienceCluster] = {}
        self._signal_threshold = signal_threshold
        self._thresholds = (maturity_master, maturity_expert, maturity_practitioner, maturity_apprentice)

    def get(self, tag: str) -> Optional[ExperienceCluster]:
        return self._clusters.get(tag)

    def all_clusters(self) -> List[ExperienceCluster]:
        return list(self._clusters.values())

    def update(self, tags: List[str], is_continuation: bool, is_conflict: bool) -> None:
        """Update clusters for all tags in a processed session."""
        score = SCORE_DEEP_USE if is_continuation else SCORE_USE
        if is_conflict:
            score += SCORE_CONFLICT
        for tag in tags:
            if tag not in self._clusters:
                self._clusters[tag] = ExperienceCluster(tag=tag, _thresholds=self._thresholds)
            self._clusters[tag].record(score, is_conflict=is_conflict)

    def update_emotion(self, tags: List[str], charge: str, intensity: float) -> None:
        """Record an emotion event for all given tags.

        charge: 'positive' | 'negative'
        intensity: 0.0–1.0
        """
        for tag in tags:
            if tag not in self._clusters:
                self._clusters[tag] = ExperienceCluster(tag=tag, _thresholds=self._thresholds)
            self._clusters[tag].record_emotion(charge, intensity)

    def load(self, rows: List[Dict[str, Any]]) -> None:
        """Hydrate from SQLite rows on bootstrap."""
        for row in rows:
            tag = row["tag"]
            self._clusters[tag] = ExperienceCluster(
                tag=tag,
                session_count=row.get("session_count", 0),
                score_sum=row.get("score_sum", 0.0),
                conflict_count=row.get("conflict_count", 0),
                last_updated=row.get("last_updated", int(time.time())),
                emotion_positive=row.get("emotion_positive", 0),
                emotion_negative=row.get("emotion_negative", 0),
                emotion_intensity_sum=row.get("emotion_intensity_sum", 0.0),
                _thresholds=self._thresholds,
            )

    def apply_decay(self, threshold_days: int = 90, rate: float = 0.01) -> List[str]:
        """Apply forgetting curve to clusters inactive longer than threshold_days.

        Returns list of tags that were decayed (for SQLite persistence).
        """
        now = int(time.time())
        decayed = []
        for tag, cluster in self._clusters.items():
            days_inactive = (now - cluster.last_updated) / 86400
            if days_inactive >= threshold_days:
                cluster.decay(days_inactive, rate)
                decayed.append(tag)
        if decayed:
            logger.info(f"Decay Engine: applied decay to {len(decayed)} clusters "
                        f"(threshold={threshold_days}d, rate={rate}/d)")
        return decayed

    def intuition_signals(self, active_tags: List[str]) -> List[Dict[str, str]]:
        """Generate Intuition Signals for tags in the current context.

        Returns list of {type, tag, message} dicts.
        Types: DO_THIS | AVOID_THIS | TENSION
        """
        signals = []
        for tag in active_tags:
            cluster = self._clusters.get(tag)
            if not cluster:
                continue
            maturity = cluster.maturity
            avg = cluster.avg_score
            conflict_rate = cluster.conflict_rate

            # TENSION: high conflict rate regardless of maturity
            if maturity in ("practitioner", "expert", "master") and conflict_rate > 0.3:
                signals.append({
                    "type": "TENSION",
                    "tag": tag,
                    "message": f"В теме «{tag}» есть неразрешённые противоречия ({cluster.conflict_count} конфликтов).",
                })
                continue

            # DO_THIS: expert+ with positive trend
            if maturity in ("expert", "master") and avg >= self._signal_threshold:
                signals.append({
                    "type": "DO_THIS",
                    "tag": tag,
                    "message": f"«{tag}» — проверенный паттерн ({cluster.session_count} сессий, score {avg:.2f}).",
                })

            # AVOID_THIS: practitioner+ with negative trend
            elif maturity in ("practitioner", "expert", "master") and avg < 0:
                signals.append({
                    "type": "AVOID_THIS",
                    "tag": tag,
                    "message": f"«{tag}» обычно приводит к проблемам в этом проекте (score {avg:.2f}).",
                })

        # Emotional pattern signals (spec §5.4)
        for tag in active_tags:
            cluster = self._clusters.get(tag)
            if not cluster:
                continue
            esig = cluster.emotion_signal
            if esig == "ATTRACT":
                signals.append({
                    "type": "ATTRACT",
                    "tag": tag,
                    "message": f"«{tag}» — положительный эмоциональный опыт (valence {cluster.emotion_valence:.2f}).",
                })
            elif esig == "REPEL":
                signals.append({
                    "type": "REPEL",
                    "tag": tag,
                    "message": f"«{tag}» — негативный эмоциональный опыт (valence {cluster.emotion_valence:.2f}).",
                })
            elif esig == "AMBIVALENT":
                signals.append({
                    "type": "AMBIVALENT",
                    "tag": tag,
                    "message": f"«{tag}» вызывает смешанные эмоции.",
                })

        return signals[:5]  # cap to avoid flooding context
