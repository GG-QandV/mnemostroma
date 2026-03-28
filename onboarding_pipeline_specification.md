# Onboarding Pipeline — Спецификация
## Mnemostroma | v1.0 | 2026-03-25

---

## 1. Суть

Автоматическая калибровка дефолтных параметров при первом запуске системы.
Не требует действий от пользователя. Не требует идеальной точности —
достаточно грубого профиля, система дотянет сама через 🤖 самоконтроль.

**Аналогия:** ребёнок не рождается с идеальной речью. Первые 10-50 сессий — это
период раннего развития, где система учится базовым паттернам конкретного юзера.

---

## 2. Триггер

```python
def should_run_onboarding(db_conn, config) -> bool:
    sessions_count = db_conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    return sessions_count == 0 and config.get("onboarding_source") is not None
```

Встроен в Conductor bootstrap как **шаг 0** (перед остальными 10 шагами).

---

## 3. Три сценария

| Сценарий | Данные | Что происходит | Результат |
|----------|--------|---------------|-----------|
| Нет истории | 0 сессий | Пропуск onboarding, дефолты | Система учится на ходу |
| Малая история | 10-50 сессий | Прогон → грубый профиль | Стартует «понимая» язык и домен |
| Большая история | 100-200+ | Прогон всех → точный профиль | Выбор юзера, не требование |

**Минимум для onboarding:** 10 сессий.
**Рекомендация:** 50 сессий.
**Обязательность:** нет — работает и с дефолтами.

---

## 4. Источники истории

| Источник | Формат | Доступ |
|----------|--------|--------|
| Claude chat export | JSON | Файл |
| ChatGPT export | JSON | Файл |
| Markdown логи | .md файлы | Директория |
| MCP-сервер агента | JSON-RPC | Runtime |
| Ручной ввод | Текстовые файлы | Директория |

### Конфигурация

```json
{
  "onboarding_source": {
    "type": "directory",
    "path": "~/chat_history/",
    "format": "markdown",
    "max_sessions": 50
  }
}
```

Или:

```json
{
  "onboarding_source": {
    "type": "mcp",
    "server": "claude-history",
    "max_sessions": 50
  }
}
```

---

## 5. Pipeline

```
Onboarding Pipeline
│
├── [1] Загрузить историю → нормализовать в [{role, content, ts}]
│
├── [2] Разбить на сессии (по timestamp gap > 30 min)
│       Ограничить: max_sessions из конфига (дефолт 50)
│
├── [3] Прогнать через Observer с ner_call_rate = 1.0
│       (GLiNER на 100% фрагментов — собираем полную статистику)
│       НЕ сохранять в Session Index — только собирать метрики
│
├── [4] Собрать профиль:
│       ├── language_distribution: {ru: 0.6, en: 0.3, mixed: 0.1}
│       ├── domain_signals: {tech: 0.8, research: 0.1, creative: 0.1}
│       ├── avg_session_length: 45 messages
│       ├── importance_distribution: {bg: 0.5, imp: 0.3, crit: 0.15, princ: 0.05}
│       ├── entity_density: 3.2 entities per session
│       ├── filter_precision: 0.72 (совпадение фильтра с GLiNER)
│       └── gliner_quality: {small_precision: 0.68, recommended: "medium"}
│
├── [5] Вычислить оптимальные параметры:
│       ├── importance_signals[] → добавить паттерны из detected language
│       ├── ner_call_rate_target → 1 - filter_precision (если 0.72 → rate 0.28)
│       ├── gliner_mode → "medium" если small_precision < 0.7
│       ├── lambda_background → выше если юзер быстро меняет темы
│       ├── tags_max_per_session → ceil(avg entity_density × 1.5)
│       ├── brief_max_chars → адаптировать к avg sentence length
│       └── session_type_classify_after_n → адаптировать к avg session length
│
├── [6] Записать config.json с персонализированными дефолтами
│
└── [7] Опционально: сохранить onboarding-сессии в Session Index
        (юзер может выбрать: «запомнить историю» или «только откалибровать»)
```

---

## 6. Что калибруется

| Параметр | Дефолт | Что onboarding определяет | Пример |
|----------|--------|--------------------------|--------|
| `importance_signals[]` | Русские ключевые слова | Язык + домен юзера | EN: добавить "decided", "blocked", "chosen" |
| `observer_ner_call_rate_target` | 0.30 | Precision фильтра на данных юзера | Фильтр промахивается 40% → rate 0.40 |
| `gliner_mode` | "small" | Precision GLiNER small на домене юзера | Tech-heavy + precision < 0.7 → "medium" |
| `lambda_background` | 0.40 | Темп смены тем | Быстрый → 0.60 |
| `tags_max_per_session` | 7 | Средняя плотность сущностей | Code-heavy → 10, conversational → 5 |
| `brief_max_chars` | 50 | Типичная длина смысловой единицы | Длинные рассуждения → 80 |
| `bge_m3_lazy_load` | true | Использует ли юзер content.save() | Coding → false (загрузить сразу) |

### Что НЕ калибруется на onboarding

| Параметр | Почему |
|----------|--------|
| Score weights (α/β/γ) | Нужны use_count данные — появятся только в runtime |
| temporal_decay_lambda | Нужна статистика возвратов — появится через недели |
| conflict_signal_threshold | Нужны реальные конфликты — появятся в работе |
| HNSWlib ef | Зависит от объёма данных — будет 0 при старте |

Эти параметры калибруются через 🤖 самоконтроль и 🧠 самообучение в runtime.

---

## 7. Длительность

| Сессий | Время onboarding | Узкое место |
|--------|-----------------|-------------|
| 10 | ~30 секунд | GLiNER inference |
| 50 | ~2 минуты | GLiNER inference |
| 200 | ~8 минут | GLiNER inference |

Одноразово при первом запуске. Не блокирует работу — можно прервать и работать с промежуточным профилем.

---

## 8. Параметры конфигурации onboarding

| Параметр | Дефолт | Шкала | Тип |
|----------|--------|-------|-----|
| `onboarding_enabled` | true | true/false | 🔧 |
| `onboarding_max_sessions` | 50 | 10–500 | 🔧 |
| `onboarding_save_history` | false | true/false | 🔧 |
| `onboarding_source` | null | object | 🔧 |

---

## 9. Интеграция в Conductor

```python
async def bootstrap(config, db_conn):
    # Шаг 0: Onboarding (НОВЫЙ)
    if should_run_onboarding(db_conn, config):
        profile = await run_onboarding(config, db_conn)
        config = apply_onboarding_profile(config, profile)
        save_config(config)
        log.info(f"Onboarding complete: {profile['sessions_processed']} sessions, "
                 f"language={profile['language_distribution']}, "
                 f"domain={profile['domain_signals']}")

    # Шаги 1-10: стандартный bootstrap (без изменений)
    await load_models(config)
    await restore_session_index(db_conn)
    # ...
```

---

*Mnemostroma | Onboarding Pipeline Specification | v1.0 | 2026-03-25*
