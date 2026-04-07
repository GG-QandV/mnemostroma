# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for Phase 5.4 — Emotional Patterns Layer.

Covers:
- ExperienceCluster emotion fields and properties
- emotion_valence / emotion_count / emotion_signal thresholds
- ExperienceIndex.update_emotion()
- ATTRACT / REPEL / AMBIVALENT in intuition_signals()
"""
import pytest
import time
from mnemostroma.memory.experience import ExperienceCluster, ExperienceIndex, _EMOTION_MIN_SAMPLES


# ── ExperienceCluster unit tests ──────────────────────────────────────────────

def test_emotion_count_zero_by_default():
    c = ExperienceCluster(tag="python")
    assert c.emotion_count == 0
    assert c.emotion_valence == 0.0
    assert c.emotion_signal is None


def test_emotion_valence_pure_positive():
    c = ExperienceCluster(tag="python", emotion_positive=4, emotion_negative=0)
    assert c.emotion_valence == pytest.approx(1.0)


def test_emotion_valence_pure_negative():
    c = ExperienceCluster(tag="legacy", emotion_positive=0, emotion_negative=4)
    assert c.emotion_valence == pytest.approx(-1.0)


def test_emotion_valence_mixed():
    c = ExperienceCluster(tag="js", emotion_positive=3, emotion_negative=1)
    # (3 - 1) / 4 = 0.5
    assert c.emotion_valence == pytest.approx(0.5)


def test_record_emotion_increments():
    c = ExperienceCluster(tag="rust")
    c.record_emotion("positive", 0.8)
    c.record_emotion("positive", 0.6)
    c.record_emotion("negative", 0.3)
    assert c.emotion_positive == 2
    assert c.emotion_negative == 1
    assert c.emotion_intensity_sum == pytest.approx(0.8 + 0.6 + 0.3)


def test_emotion_signal_none_below_min_samples():
    c = ExperienceCluster(tag="go")
    for _ in range(_EMOTION_MIN_SAMPLES - 1):
        c.record_emotion("positive", 1.0)
    assert c.emotion_signal is None


def test_emotion_signal_attract():
    c = ExperienceCluster(tag="rust")
    # Need >= _EMOTION_MIN_SAMPLES, valence >= 0.6
    # 4 positive, 0 negative → valence = 1.0
    for _ in range(4):
        c.record_emotion("positive", 0.9)
    assert c.emotion_signal == "ATTRACT"


def test_emotion_signal_repel():
    c = ExperienceCluster(tag="legacy_code")
    # 4 negative, 0 positive → valence = -1.0
    for _ in range(4):
        c.record_emotion("negative", 0.7)
    assert c.emotion_signal == "REPEL"


def test_emotion_signal_ambivalent():
    c = ExperienceCluster(tag="meetings")
    # Need >= 6 samples, |valence| <= 0.3
    # 3 positive, 3 negative → valence = 0.0
    for _ in range(3):
        c.record_emotion("positive", 0.5)
    for _ in range(3):
        c.record_emotion("negative", 0.5)
    assert c.emotion_signal == "AMBIVALENT"


def test_emotion_signal_ambivalent_requires_6_samples():
    c = ExperienceCluster(tag="meetings")
    # Only 4 samples with valence 0 — not enough for AMBIVALENT
    for _ in range(2):
        c.record_emotion("positive", 0.5)
    for _ in range(2):
        c.record_emotion("negative", 0.5)
    # |valence| == 0 but total == 4 < 6
    assert c.emotion_signal is None


def test_to_dict_includes_emotion_fields():
    c = ExperienceCluster(tag="python", emotion_positive=3, emotion_negative=1,
                          emotion_intensity_sum=2.4)
    d = c.to_dict()
    assert "emotion_positive" in d
    assert "emotion_negative" in d
    assert "emotion_intensity_sum" in d
    assert "emotion_valence" in d
    assert "emotion_signal" in d


# ── ExperienceIndex tests ──────────────────────────────────────────────────────

def test_update_emotion_creates_cluster():
    idx = ExperienceIndex()
    idx.update_emotion(["python", "backend"], "positive", 0.8)
    c = idx.get("python")
    assert c is not None
    assert c.emotion_positive == 1
    assert c.emotion_intensity_sum == pytest.approx(0.8)


def test_update_emotion_multiple_tags():
    idx = ExperienceIndex()
    idx.update_emotion(["a", "b", "c"], "negative", 0.5)
    for tag in ["a", "b", "c"]:
        assert idx.get(tag).emotion_negative == 1


def test_load_restores_emotion_fields():
    idx = ExperienceIndex()
    now = int(time.time())
    idx.load([{
        "tag": "rust",
        "session_count": 5,
        "score_sum": 3.0,
        "conflict_count": 0,
        "last_updated": now,
        "emotion_positive": 4,
        "emotion_negative": 1,
        "emotion_intensity_sum": 2.5,
    }])
    c = idx.get("rust")
    assert c.emotion_positive == 4
    assert c.emotion_negative == 1
    assert c.emotion_intensity_sum == pytest.approx(2.5)


def test_load_missing_emotion_fields_defaults_to_zero():
    idx = ExperienceIndex()
    now = int(time.time())
    idx.load([{
        "tag": "legacy",
        "session_count": 2,
        "score_sum": 1.0,
        "conflict_count": 0,
        "last_updated": now,
        # emotion fields absent (old DB row)
    }])
    c = idx.get("legacy")
    assert c.emotion_positive == 0
    assert c.emotion_negative == 0
    assert c.emotion_intensity_sum == pytest.approx(0.0)


# ── intuition_signals includes emotional signals ──────────────────────────────

def test_intuition_signals_attract():
    idx = ExperienceIndex()
    for _ in range(4):
        idx.update_emotion(["rust"], "positive", 0.9)
    signals = idx.intuition_signals(["rust"])
    types = [s["type"] for s in signals]
    assert "ATTRACT" in types


def test_intuition_signals_repel():
    idx = ExperienceIndex()
    for _ in range(4):
        idx.update_emotion(["xml"], "negative", 0.8)
    signals = idx.intuition_signals(["xml"])
    types = [s["type"] for s in signals]
    assert "REPEL" in types


def test_intuition_signals_ambivalent():
    idx = ExperienceIndex()
    for _ in range(3):
        idx.update_emotion(["meetings"], "positive", 0.5)
    for _ in range(3):
        idx.update_emotion(["meetings"], "negative", 0.5)
    signals = idx.intuition_signals(["meetings"])
    types = [s["type"] for s in signals]
    assert "AMBIVALENT" in types


def test_intuition_signals_capped_at_5():
    idx = ExperienceIndex()
    # Create many tags all with ATTRACT signal
    for tag in [f"tag{i}" for i in range(10)]:
        for _ in range(4):
            idx.update_emotion([tag], "positive", 0.9)
    signals = idx.intuition_signals([f"tag{i}" for i in range(10)])
    assert len(signals) <= 5
