# Onboarding Pipeline Specification
> μνήμη + στрῶμα | Phase: Bootstrap | 2026-04-01

---

## 1. Цель
Onboarding Pipeline ("Шаг 0") обеспечивает мгновенную "прокачку" памяти нового агента на основе его накопленной истории (экспорты чатов, логи предыдущих IDE сессий). Это избавляет пользователя от необходимости обучать систему с нуля.

## 2. Шаг 0: Bootstrap
При первом запуске системы (`mnemostroma.db` пуста или содержит < 5 сессий) Conductor предлагает запустить Onboarding.

- **Минимальный набор**: 10 сессий.
- **Оптимальный набор**: 50 сессий.
- **Источники**: `history.json` (Claude export), `chat.txt`, или кастомный формат импорта.

## 3. Калибровочный агент
Система запускает фоновый процесс, который "проигрывает" историю через стандартный Observer Pipeline, но с ускоренными параметрами:
1. **Batch Processing**: обработка сессий пачками.
2. **Auto-Tagging**: агрессивное извлечение тегов.
3. **Statistical Baseline**: сбор средних значений `importance`, `relevance` и плотности сущностей.

## 4. Результат калибровки
По итогам Onboarding обновляется `config.json` с персональными порогами:
- `tag_score_threshold`: индивидуально (0.4 - 0.7)
- `dissolver_decay_rate`: на основе частоты сессий
- `ner_call_rate`: адаптивно под стиль общения пользователя

## 5. Интеграция с Conductor
```python
# conductor.py logic
if db.session_count() < config.min_onboarding_sessions:
    conductor.trigger_onboarding(history_source)
```

## 6. MCP Skill
`ctx.calibrate(path)` — инструмент для принудительного запуска пайплайна на новых данных.

---
*Mnemostroma Onboarding Spec | v1.0 | 2026-04-01*
