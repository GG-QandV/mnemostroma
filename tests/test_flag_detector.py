# SPDX-License-Identifier: FSL-1.1-MIT
import pytest
from mnemostroma.observer.flag_detector import (
    detect_outcome,
    detect_user_pin,
    detect_multi_session,
    detect_all_flags,
)


class TestOutcome:
    def test_success_ru(self):
        assert detect_outcome("Рефакторинг завершено успешно") == "success"

    def test_success_en(self):
        assert detect_outcome("All tests passed, build is green") == "success"

    def test_failure_ru(self):
        assert detect_outcome("Не удалось подключить базу, ошибка") == "failure"

    def test_failure_en(self):
        assert detect_outcome("Build failed with 3 errors") == "failure"

    def test_abandoned_ru(self):
        assert detect_outcome("Отказались от этого подхода, свернули") == "abandoned"

    def test_abandoned_en(self):
        assert detect_outcome("Feature was cancelled and dropped") == "abandoned"

    def test_failure_beats_success(self):
        """Failure has priority — negative memory is stronger."""
        assert detect_outcome("Тесты прошли но деплой упал с ошибкой") == "failure"

    def test_pending_no_signals(self):
        assert detect_outcome("Обсуждаем варианты архитектуры") == "pending"

    def test_neutral_mixed(self):
        """No strong signals → pending."""
        assert detect_outcome("Посмотрели на код, ничего особенного") == "pending"


class TestUserPin:
    def test_pin_ru_zapomni(self):
        assert detect_user_pin("Запомни это на будущее") is True

    def test_pin_ru_ne_zabud(self):
        assert detect_user_pin("Не забудь про лимит памяти") is True

    def test_pin_ru_prigoditsya(self):
        assert detect_user_pin("Это ещё пригодится") is True

    def test_pin_en_remember(self):
        assert detect_user_pin("Remember this for later") is True

    def test_pin_en_keep_mind(self):
        assert detect_user_pin("Keep in mind the RAM limit") is True

    def test_no_pin(self):
        assert detect_user_pin("Обычный текст без инструкций") is False


class TestMultiSession:
    def test_continuation_ru(self):
        assert detect_multi_session("Продолжаем работу над рефакторингом") is True

    def test_previous_session_ru(self):
        assert detect_multi_session("В прошлой сессии мы начали") is True

    def test_next_step_ru(self):
        assert detect_multi_session("Следующий этап — тестирование") is True

    def test_continuation_en(self):
        assert detect_multi_session("Continuing from last session") is True

    def test_no_continuation(self):
        assert detect_multi_session("Начинаем новый проект с нуля") is False


class TestDetectAll:
    def test_combined(self):
        text = "Продолжаем рефакторинг. Всё работает. Запомни эту конфигурацию."
        flags = detect_all_flags(text)
        assert flags["outcome"] == "success"
        assert flags["user_pin"] is True
        assert flags["multi_session"] is True

    def test_empty_text(self):
        flags = detect_all_flags("")
        assert flags["outcome"] == "pending"
        assert flags["user_pin"] is False
        assert flags["multi_session"] is False
