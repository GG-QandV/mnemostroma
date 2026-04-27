# SPDX-License-Identifier: FSL-1.1-MIT
"""Tests for memory intent detector."""

from mnemostroma.integration.http_proxy import _detect_memory_intent


def test_no_signal():
    assert _detect_memory_intent("напиши функцию сортировки") == 0.0


def test_single_signal():
    score = _detect_memory_intent("сделай как в прошлый раз")
    assert 0.3 <= score <= 0.5


def test_multi_signal():
    score = _detect_memory_intent("помнишь, мы договорились как раньше?")
    assert score >= 0.8


def test_english_signal():
    score = _detect_memory_intent("do it like last time, remember?")
    assert score >= 0.4


def test_empty():
    assert _detect_memory_intent("") == 0.0
