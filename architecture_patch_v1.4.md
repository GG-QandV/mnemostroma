# Architecture — Патч v1.4
## Дата: 2026-03-24 | Добавлено: embedding_model_version в SQLite, документация разницы весов Score

---

## Патч 1: embedding_model_version в SQLite (WP-10)

### Изменения схемы

Добавить колонку версии модели эмбеддинга в таблицы `sessions` и `content_versions`:

```sql
-- Версионирование модели эмбеддинга
ALTER TABLE sessions ADD COLUMN embedding_model_version TEXT DEFAULT 'embeddinggemma-300m-int8-v1';
ALTER TABLE content_versions ADD COLUMN embedding_model_version TEXT DEFAULT 'bge-m3-int8-v1';

-- Таблица реестра моделей
CREATE TABLE IF NOT EXISTS embedding_model_registry (
    model_key        TEXT PRIMARY KEY,   -- 'embeddinggemma-300m-int8-v1'
    model_name       TEXT,               -- human-readable
    dim              INTEGER,            -- 512
    quantization     TEXT,               -- 'int8'
    registered_at    INTEGER,            -- unix timestamp
    is_current       INTEGER DEFAULT 0   -- 1 = текущая активная модель
);
```

### Поведение Recalibrator при смене модели

При обнаружении новой версии модели эмбеддинга Recalibrator выполняет следующую последовательность:

1. Вставить новую модель в `embedding_model_registry`, установить `is_current=1`, старой записи `is_current=0`
2. Пересчитать эмбеддинги для сессий в RAM с устаревшей версией
3. Обновить поле `embedding_model_version` у каждой затронутой сессии
4. Архивные сессии: ленивое обновление при следующем вызове `ctx.load()`
5. HNSWlib: blue-green swap (см. `tuner_specification_v1.4.md`)

### Правило совместимости поиска

- `ctx.semantic()` запрашивает ТОЛЬКО сессии, где `embedding_model_version` = текущая активная модель
- ИЛИ если индекс ещё не перестроен: fallback на cosine distance с предупреждением о несоответствии версии в логах
- **Никогда не возвращать результаты с неправильной версией молча**

```
COMPATIBILITY RULE:
  query_model == session.embedding_model_version  →  обычный поиск
  query_model != session.embedding_model_version  →  fallback + WARNING в логах
  index not rebuilt yet                           →  cosine fallback + WARNING
```

---

## Патч 2: Документация разницы весов Score (NEW-02)

### Два профиля весов

Система намеренно использует ДВА различных профиля весов Score. Это задокументированное поведение, не баг.

```
SCORE PROFILES:
┌─────────────────────────────────────────────────────────────────┐
│ Profile A — OBSERVER WRITE (при сохранении сессии)              │
│ Score = 0.5×R + 0.3×T + 0.2×I                                  │
│ Приоритет: балансированный. Равный вес свежести и важности.     │
│ Цель: правильно оценить что сохранить в RAM.                    │
├─────────────────────────────────────────────────────────────────┤
│ Profile B — SEMANTIC SEARCH (при ctx.semantic() запросе)        │
│ Score = 0.6×R + 0.3×T + 0.1×I                                  │
│ Приоритет: релевантность. Семантическое совпадение важнее всего.│
│ Цель: найти самое подходящее для текущего запроса.              │
└─────────────────────────────────────────────────────────────────┘
```

### Обоснование раздельных профилей

| Аспект | Profile A (Write) | Profile B (Search) |
|--------|-------------------|--------------------|
| Назначение | Решение о хранении в RAM | Ответ на семантический запрос |
| Релевантность (R) | 0.5 | 0.6 |
| Временной распад (T) | 0.3 | 0.3 |
| Важность (I) | 0.2 | 0.1 |
| Логика | Важность влияет на то, *что хранить* | Семантическое совпадение — основной сигнал при поиске |

- **Write profile** балансирует решения о хранении (важность имеет значение для того, что оставлять)
- **Read profile** максимизирует релевантность запроса (семантическое совпадение — первичный сигнал)
- **Оба профиля** уважают временной распад (β=0.3 идентично)

### Конфигурационные ключи

```json
{
  "score_weights_write":  {"relevance": 0.5, "temporal": 0.3, "importance": 0.2},
  "score_weights_search": {"relevance": 0.6, "temporal": 0.3, "importance": 0.1}
}
```

### Затронутые компоненты

| Компонент | Использует профиль | Метод |
|-----------|-------------------|-------|
| Observer.save_session() | Write (Profile A) | score_weights_write |
| ctx.semantic() | Search (Profile B) | score_weights_search |
| Consolidation Worker | Write (Profile A) | score_weights_write |
| RAM eviction ranking | Write (Profile A) | score_weights_write |

---

*Architecture Patch v1.4 | 2026-03-24 | WP-10, NEW-02*
