# RAM-First Context Management System

## Архитектура v1.0

---

## 1. Концепция и философия

Система управления контекстом для AI-агентов, построенная по принципу **RAM-first** — всё что нужно агенту прямо сейчас живёт в оперативной памяти. Персистентность — асинхронно на диск, без блокировки агента.

### Ключевые принципы

1. **Агент никогда не пишет контекст сам** — этим занимается независимый Observer
2. **Два независимых потока записи** — смысловой контекст и контент не пересекаются при записи
3. **Теги = сигнал, текст = шум** — в горячем контексте только сжатое представление
4. **Без фреймворков** — только ONNX Runtime + numpy + tokenizers
5. **Три слоя сессионной памяти** — смысловой, якорный, прецизионный

### Человеческая модель памяти (основа)

Система воспроизводит трёхуровневую модель Atkinson-Shiffrin:

| Уровень               | Человек                    | Наша система                                |
| --------------------- | -------------------------- | ------------------------------------------- |
| Сенсорная память      | фильтрация I/O до сознания | Observer: фильтр сигналов важности          |
| Рабочая память        | 7±2 элементов, быстро      | Session Index в RAM, max 9 active_variables |
| Долговременная память | эпизоды + семантика        | SQLite cold storage + MatrixSearch global index  |

---

## 2. Два независимых потока

```
                    I/O агента
                        │
          ┌─────────────┴──────────────┐
          │                            │
    ПОТОК 1: OBSERVER              ПОТОК 2: AGENT CONTENT
    (автономный sidecar)           (осознанная запись)
          │                            │
    Что пишет:                   Что пишет:
    - теги смысла                - контент (код/текст/сцена)
    - brief (50 символов)        - версии контента
    - якоря (телефон/адрес)      - content_tags[]
    - прецизионные данные        - why_changed
    - векторы сессии             - векторы версий
          │                            │
          ▼                            ▼
    Session Index (RAM)          Content Index (RAM)
    MatrixSearch Session         MatrixSearch Content
    SQLite: sessions             SQLite: content_versions
          │                            │
          └──────────┬─────────────────┘
                     │  связь: session_id
                     ▼
              SQLite WAL (диск)
```

**PersistenceLayer (v1.7.1, Phase 9.2):** Для обеспечения инварианта RAM ⊆ DISK введён формальный слой персистентности. Он разделяет бизнес-логику WorkingMemory и детали реализации SQLite. Все критические операции записи (якоря, опыт, сессии) теперь выполняются через `await ctx.persistence.*`, что исключает потерю данных при завершении процесса («fire-and-forget» запрещён для структурных изменений).

**Принципиальное различие:** Observer не знает про контент — он видит только смысл процесса.
1. **Агент НИКОГДА не пишет память** — только Observer
2. **Embedding НИКОГДА не удаляется** — MatrixSearch хранит вечно
гирует её.

---

## 3. Ветка 1: Сессионный контекст (Observer)

### 3.1 Трёхслойная структура

**Слой 1 — Смысловой (теги и семантика)**

```json
{
  "session_id": "session_047",
  "tags": ["#система_памяти", "#решение", "#архитектура"],
  "brief": "Построена 6-слойная система инструментов контекста",
  "why_log": "Нужна RAM-first архитектура без фреймворков",
  "importance": "critical",
  "conflict_flag": false,
  "embedding": "[float16 × 512]",
  "created_at": 1741216800,
  "updated_at": 1741216800,
  "age_signal": "fresh"
}
```

**Слой 2 — Якорный (структурированные факты)**

```json
{
  "anchors": [
    {"type": "decision", "value": "EmbeddingGemma INT8"},
    {"type": "number",   "value": "197MB"},
    {"type": "person",   "value": "Алехандро"},
    {"type": "link",     "value": "github.com/urchade/GLiNER"},
    {"type": "deadline", "value": "2026-03-15"}
  ]
}
```

**Слой 3 — Прецизионный (дословная точность)**

```json
{
  "precision_id": "p_047_003",
  "session_id": "session_047",
  "type": "concept",
  "value": "Семантическая компрессия — хранение 3-7 тегов вместо полного текста",
  "context_tag": "#память #компрессия",
  "importance": "critical",
  "created_at": 1741216800
}
```

### 3.2 Жизненный цикл сессии

```
СТАРТ:    session_bridge загружается в контекст агента
РАБОТА:   Observer пишет в RAM async, агент читает мгновенно  
КОНЕЦ:    async flush → SQLite + MatrixSearch update
АРХИВ:    age_signal меняется: fresh → actual → stale → archive
```

### 3.3 Скользящее окно

В RAM держать последние **200 сессий** (~200MB Session Index).
Старые сессии — только в SQLite, доступны через `ctx.full(session_id)`.

---

## 4. Ветка 2: Контентная (Agent)

### 4.1 Жизненный цикл проекта

```
СТАРТ ПРОЕКТА:
  Создаётся контентный контекст
  RAM: чистый content index

РАБОТА:
  Блоки добавляются и версионируются
  RAM: только активные блоки (~50-200 блоков)

ЗАВЕРШЕНИЕ:
  status = "completed"
  RAM → flush → SQLite (архив)
  RAM очищается

СЛЕДУЮЩИЙ ПРОЕКТ:
  Чистый контекст
  Поиск по архиву через ctx.semantic()
  Стек v1.7: marker(), Entity/Emotion/Atmosphere, Dreamer, t_rel, Emotional Patterns
```

### 4.2 Структура контентного блока

```json
{
  "content_id": "func_auth_v2",
  "session_id": "session_031",
  "content_type": "function",
  "parent_id": "module_auth",
  "versions": [
    {
      "v": 1,
      "content_hash": "a3f2b1c9...",
      "content_raw": "[lz4 compressed bytes]",
      "content_tags": ["#авторизация", "#JWT"],
      "tags_verified": false,
      "why_changed": null,
      "status": "rejected",
      "rejected_reason": "не обрабатывает истечение токена",
      "embedding": "[float16 × 512]",
      "created_at": 1741200000
    },
    {
      "v": 2,
      "content_hash": "b7c1d4e8...",
      "content_raw": "[lz4 compressed bytes]",
      "content_tags": ["#авторизация", "#JWT", "#expiry"],
      "tags_verified": true,
      "why_changed": "добавлена обработка истечения токена",
      "status": "active",
      "embedding": "[float16 × 512]",
      "created_at": 1741216800
    }
  ]
}
```

### 4.3 Верификация тегов

```python
# Алгоритм верификации
for tag in content_tags:
    tag_vector = embed(tag)
    content_vector = embed(content_raw)
    similarity = cosine(tag_vector, content_vector)
    if similarity > 0.65:
        verified.append(tag)  # ✅
    else:
        questionable.append(tag)  # ⚠️

# GLiNER предлагает дополнительные теги
extra_tags = gliner.predict(content_raw, entity_types=[
    "технология", "паттерн", "ограничение", "зависимость"
])
```

---

## 5. Observer — детальная схема работы

### 5.1 Пайплайн Observer

```
Агент генерирует output
        │
        ▼ (async, не блокирует агента)
[Шаг 1: Детерминированный фильтр]  ~0.1ms  0MB
  Regex + signal detection:
  - importance signals: "решили", "запрет", "итог", "блокер"
  - conflict signals: "но", "изменили", "отменили", "вместо"
  - precision signals: URL, телефон, email, числа, формулы
  - anchor signals: имена, даты, координаты
        │
        ├── precision detected → Precision Log немедленно
        ├── anchor detected → Anchor Layer немедленно
        │
        ▼
[Шаг 2: HybridNER (DistilBERT int8 + Regex)]  ~10ms  ~178MB
  NER для извлечения решений, запретов, технологий и артефактов
  distilbert-ner int8 (170MB) + patterns
        │
        ▼
[Шаг 3: multilingual-e5-small int8]  ~15ms  ~420MB
  текст → вектор 384d
        │
        ▼
[Шаг 4: TinyBERT реранкинг (lazy)]  ~6ms  8MB
  проверка: вектор релевантен текущему контексту?
        │
        ▼
[Шаг 5: Score = R×0.5 + T×0.3 + I×0.2]  ~1ms  0MB
  R = cosine similarity с текущим intent
  T = freshness (e^(-λ×age))
  I = importance_weight (0.1 / 0.5 / 1.0)
        │
        ▼
[Шаг 6: Сохранение]  ~1ms
  → RAM: Session Index dict update
  → RAM: MatrixSearch Session add_item
  async:
  → SQLite WAL: sessions INSERT/UPDATE
  → Precision Log: если precision_flag
  → Anchor Layer: если anchor_flag (marker() detected)
```

## Model Stack (Final v3, 2026-03-31)

| Role | Model | Dim | File | RAM |
|------|-------|-----|------|-----|
| Session & Content Embedder | multilingual-e5-small int8 | 384 | models/multilingual-e5-small/ | ~138MB ONNX + ~270MB tokenizer |
| NER | HybridNER (DistilBERT + regex) | — | models/distilbert-ner/ | ~178MB |
| Reranker | TinyBERT-L2-v2 | — | models/tinybert-l2-v2/ | 8MB (lazy) |
| **Total RSS** | | | | **631MB** |

Budget: 700MB hard limit. Margin: 69MB.

### 5.2 Сигналы важности (детерминированный фильтр)

```python
IMPORTANCE_SIGNALS = {
    "critical": [
        "решили", "выбрали", "запрет", "нельзя", "блокер",
        "итог", "финально", "архитектура", "принципиально"
    ],
    "important": [
        "важно", "артефакт", "файл", "конфиг", "схема",
        "используем", "зависимость", "требование"
    ],
    "conflict": [
        "но", "однако", "противоречит", "изменили",
        "отменили", "вместо", "переделали", "не подходит"
    ],
    "precision": [
        r"https?://\S+",           # URL
        r"\+?\d[\d\s\-\(\)]{7,}", # телефон
        r"[\w.]+@[\w.]+\.\w+",    # email
        r"\d+[.,]\d+\s*(MB|GB|ms|KB|%|руб|\$|€)",  # числа с единицами
    ]
}
```

---

## 6. MCP Инструменты — полный набор

### 6.1 Инструменты записи (только Observer и Agent)

| Инструмент              | Кто вызывает | Операция                                   |
| ----------------------- | ------------ | ------------------------------------------ |
| `ctx.save(entity)`      | Observer     | Сохранить сущность в RAM + async SQLite    |
| `ctx.update(id, delta)` | Observer     | Обновить только изменённые поля            |
| `ctx.flag(id, flag)`    | Observer     | Поставить метку: conflict/archive/critical |
| `ctx.precision(item)`   | Observer     | Сохранить прецизионный артефакт            |
| `content.save(block)`   | Agent        | Сохранить контентный блок + версию         |
| `content.tag(id, tags)` | Agent        | Добавить/обновить теги к блоку             |

### 6.2 Инструменты чтения (Agent использует)

| Инструмент              | Источник        | Latency | Возвращает                        |
| ----------------------- | --------------- | ------- | --------------------------------- |
| `ctx.active()`          | RAM dict        | <0.01ms | active_variables + intent_summary |
| `ctx.get(id)`           | RAM dict        | <0.01ms | brief + tags (не full)            |
| `ctx.search(tags[])`    | RAM dict        | <0.1ms  | список brief + scores             |
| `ctx.semantic(query)`   | MatrixSearch    | <1ms    | top-K session_ids + scores        |
| `ctx.anchors(type)`     | RAM dict        | <0.1ms  | якоря по типу                     |
| `ctx.precision(type)`   | RAM dict        | <0.1ms  | прецизионные данные               |
| `ctx.full(id)`          | SQLite          | <0.5ms  | полный content_full               |
| `content.search(query)` | MatrixSearch Content | <1ms    | top-K content_ids                 |
| `content.get(id, v)`    | RAM + SQLite    | <1ms    | контентный блок                   |
| `ctx.bridge()`          | RAM dict        | <0.01ms | session_handoff для нового агента |

### 6.3 Управление

| Инструмент             | Операция                                       |
| ---------------------- | ---------------------------------------------- |
| `ctx.decay()`          | Автоматический пересчёт age_signal всех сессий |
| `ctx.evict(n)`         | Выгрузить N старейших сессий из RAM в SQLite   |
| `ctx.sync()`           | Принудительный flush RAM → SQLite (async)      |
| `ctx.load(session_id)` | Загрузить сессию из SQLite в RAM               |
| `ctx.status()`         | RAM usage, кол-во сессий, latency stats        |

---

## 7. Схема данных SQLite

```sql
-- Ветка 1: сессионный контекст
CREATE TABLE sessions (
    session_id    TEXT PRIMARY KEY,
    created_at    INTEGER,
    updated_at    INTEGER,
    importance    TEXT,
    age_signal    TEXT,
    tags          TEXT,    -- JSON array
    brief         TEXT,    -- max 50 символов
    why_log       TEXT,
    intent        TEXT,
    conflict      INTEGER DEFAULT 0,
    content_full  TEXT,    -- полный лог (опционально)
    session_type  TEXT     -- context / content / research
);

CREATE INDEX idx_sessions_date       ON sessions(created_at);
CREATE INDEX idx_sessions_importance ON sessions(importance);
CREATE INDEX idx_sessions_age        ON sessions(age_signal);
CREATE INDEX idx_sessions_type       ON sessions(session_type);

-- Якорный слой
CREATE TABLE anchors (
    anchor_id   TEXT PRIMARY KEY,
    session_id  TEXT REFERENCES sessions(session_id),
    type        TEXT,   -- decision/phone/address/person/number/date
    value       TEXT,
    context_tag TEXT,
    importance  TEXT,
    created_at  INTEGER
);

CREATE INDEX idx_anchors_type    ON anchors(type);
CREATE INDEX idx_anchors_session ON anchors(session_id);
CREATE INDEX idx_anchors_value   ON anchors(value);

-- Прецизионный слой
CREATE TABLE precision_log (
    precision_id  TEXT PRIMARY KEY,
    session_id    TEXT REFERENCES sessions(session_id),
    type          TEXT,   -- link/concept/quote/formula/data
    value         TEXT,   -- дословно, без изменений
    context_tag   TEXT,
    importance    TEXT,
    created_at    INTEGER
);

CREATE INDEX idx_precision_type    ON precision_log(type);
CREATE INDEX idx_precision_session ON precision_log(session_id);

-- Ветка 2: контентная
CREATE TABLE content_blocks (
    content_id   TEXT PRIMARY KEY,
    session_id   TEXT REFERENCES sessions(session_id),
    content_type TEXT,   -- function/class/chapter/scene/config
    parent_id    TEXT,
    project_id   TEXT,
    status       TEXT    -- active/completed/archived
);

CREATE TABLE content_versions (
    content_id      TEXT REFERENCES content_blocks(content_id),
    version         INTEGER,
    content_hash    TEXT,
    content_raw     BLOB,     -- lz4 compressed
    content_diff    TEXT,
    content_tags    TEXT,     -- JSON array
    tags_verified   INTEGER DEFAULT 0,
    why_changed     TEXT,
    status          TEXT,     -- draft/active/rejected/archived
    rejected_reason TEXT,
    embedding       BLOB,     -- float16 512d binary
    created_at      INTEGER,
    PRIMARY KEY (content_id, version)
);

CREATE INDEX idx_cv_status  ON content_versions(status);
CREATE INDEX idx_cv_hash    ON content_versions(content_hash);
CREATE INDEX idx_cv_session ON content_versions(content_id);
```

---

## 8. Формула ранжирования Score

\[ Score = (\alpha \times R) + (\beta \times T) + (\gamma \times I) \]
\[ (numpy MatrixSearch replaces hnswlib — ADR-002) \]

где:

- **R** — семантическая релевантность (cosine similarity с запросом)
- **T** — временна́я свежесть: \( e^{-\lambda \times age\_days} \), λ = 0.05
- **I** — важность: critical=1.0 / important=0.5 / background=0.1
- **α = 0.5, β = 0.3, γ = 0.2** — базовые веса (настраиваемые)

### Критерии определения важности (I)

| Критерий                         | Уровень    |
| -------------------------------- | ---------- |
| Сущность блокирует следующий шаг | critical   |
| Явный сигнал: "решили", "итог"   | critical   |
| Упоминается повторно (≥3 раз)    | important  |
| Связана с open_issues[]          | important  |
| Артефакт (файл/конфиг/схема)     | important  |
| Всё остальное                    | background |

---

## 9. Жизненный цикл данных

```
Создание:   age_signal = "fresh"      Score T = 1.0
24 часа:    age_signal = "actual"     Score T = 0.95
7 дней:     age_signal = "stale"      Score T = 0.70
30 дней:    age_signal = "archive"    Score T = 0.22
90 дней:    evict из RAM → SQLite only
```

### Правила eviction из RAM

1. `age_signal = "archive"` AND `importance != "critical"` → evict
2. RAM > 80% лимита → evict N старейших по Score
3. `valid_until` истёк → evict немедленно
4. `conflict_flag = true` → держать до разрешения конфликта

---

## 10. Session Bridge — передача контекста

При старте каждой новой сессии или при смене агента:

```json
{
  "context_brief": "Построена RAM-first система контекста, 2 ветки",
  "intent_summary": "Создать операционную систему памяти для AI-агентов",
  "active_variables": [
    "EmbeddingGemma INT8 52MB",
    "BGE-M3 INT8 145MB",
    "Observer async sidecar",
    "Session + Content ветки",
    "SQLite WAL cold storage"
  ],
  "open_issues": [
    "не выбрана точка входа для MVP",
    "нет тестов системы на реальном проекте"
  ],
  "last_decisions": [
    "отказались от Реранкера A (MiniLM)",
    "контентная ветка в RAM полностью",
    "скользящее окно 200 сессий для Session Index"
  ],
  "next_action": "Реализовать Observer + Session Index как MVP",
  "session_id": "session_047",
  "timestamp": 1741216800
}
```
