# Observer — Детальная спецификация
## RAM-First Context System v1.3
## Патч: urgency_policy | Дата: 2026-03-06

> **Изменения v1.3:** добавлены `detect_urgency()` и `detect_principle()` в шаг [2],
> urgency_index обновляется в шаге [6], Consolidation Worker проверяет истёкшие дедлайны.
> Остальные разделы без изменений относительно v1.0.

---

## 1. Роль Observer в системе

Observer — это автономный async coroutine, который наблюдает за всем I/O агента
и строит смысловой контекст. Агент никогда не пишет контекст сам.

```
Агент -> генерирует output
             |
             |-> Агент продолжает работу (не блокируется)
             |
             -> Observer получает копию output async
                        |
                  [обрабатывает самостоятельно]
                        |
                  пишет в RAM + async SQLite
```

Ключевое свойство: Observer — единственный кто имеет право писать в Session Index,
Anchor Layer, Precision Log и urgency_index. Агент эти данные только читает.

---

## 2. Полный пайплайн Observer

### Шаг 1: Перехват I/O (0ms overhead)

```python
async def observer_intercept(agent_output: str, session_id: str):
    asyncio.create_task(observer_process(agent_output, session_id))
    # Агент продолжает немедленно
```

### Шаг 2: Детерминированный фильтр (~0.2ms, 0MB RAM overhead)

> **v1.3:** добавлены `detect_urgency()` и `detect_principle()`.
> Суммарный overhead: +0.1ms (regex). Принцип: тот же детерминированный шаг.

```python
import re

CRITICAL  = ["решили","выбрали","запрет","нельзя","блокер","итог","финально"]
IMPORTANT = ["важно","артефакт","используем","требование","зависимость"]
CONFLICT  = ["но ","однако","противоречит","изменили","отменили","вместо"]

PRECISION_PATTERNS = {
    "link":   r"https?://[^\s]+",
    "email":  r"[\w.]+@[\w.]+\.[\w]+",
    "phone":  r"\+?\d[\d\s\-\(\)]{7,}",
    "number": r"\d+[.,]?\d*\s*(MB|GB|ms|KB|%|руб|\$|EUR)",
}

# --- НОВОЕ v1.3: urgency сигналы ---
URGENCY_SIGNALS = {
    "deadline_h": [
        "через час","через два часа","в течение часа",
        "in 1 hour","in 2 hours","asap","срочно сейчас",
    ],
    "deadline_d": [
        "сегодня","завтра","today","tomorrow",
        "до конца дня","by eod","дедлайн сегодня","deadline today",
    ],
    "deadline_w": [
        "на этой неделе","до конца недели","this week",
        "by friday","до пятницы","через неделю","in a week",
    ],
}

# --- НОВОЕ v1.3: principle сигналы ---
PRINCIPLE_SIGNALS = [
    "никогда","всегда","запомни это","это принцип",
    "правило проекта","архитектурное решение",
    "never","always","remember this","non-negotiable",
    "project rule","architectural principle",
]

DEADLINE_PATTERN = re.compile(
    r'\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?'
    r'|\d{4}-\d{2}-\d{2}'
    r'|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2})\b',
    re.IGNORECASE
)

# --- НОВОЕ v1.3 ---
def detect_urgency(text: str) -> tuple:
    """
    Возвращает (UrgencyLevel, deadline_value_str | None).
    Latency: ~0.1ms (regex).
    """
    t = text.lower()
    for level in ("deadline_h", "deadline_d", "deadline_w"):
        if any(sig in t for sig in URGENCY_SIGNALS[level]):
            m = DEADLINE_PATTERN.search(text)
            return level, (m.group(0) if m else None)
    m = DEADLINE_PATTERN.search(text)
    if m:
        return "deadline_d", m.group(0)  # явная дата без сигнальных слов
    return "none", None

# --- НОВОЕ v1.3 ---
def detect_principle(text: str) -> bool:
    """
    True → importance=principle.
    Пользователь явно зафиксировал принцип ("никогда", "always"...).
    Latency: ~0.05ms.
    """
    t = text.lower()
    return any(sig in t for sig in PRINCIPLE_SIGNALS)

def deterministic_filter(text: str) -> dict:
    t = text.lower()
    importance = "background"
    if any(w in t for w in CRITICAL):    importance = "critical"
    elif any(w in t for w in IMPORTANT): importance = "important"

    # v1.3: principle переопределяет importance
    if detect_principle(text):
        importance = "principle"

    conflict = any(w in t for w in CONFLICT)
    precision_items = []
    for ptype, pat in PRECISION_PATTERNS.items():
        for m in re.findall(pat, text):
            precision_items.append({"type": ptype, "value": m})

    # v1.3: urgency детекция
    urgency, deadline_val = detect_urgency(text)

    needs_ner = not (importance in ("critical", "principle") and precision_items)
    return {
        "importance":      importance,
        "conflict":        conflict,
        "precision_items": precision_items,
        "needs_ner":       needs_ner,
        "urgency":         urgency,        # NEW v1.3
        "deadline_val":    deadline_val,   # NEW v1.3
    }
```

### Шаг 3: GLiNER NER (~8ms) — только если нужен

```python
async def extract_entities(text: str, gliner_session) -> list:
    entity_types = [
        "решение","запрет","артефакт","технология",
        "концепция","вопрос","человек","продукт"
    ]
    inputs  = prepare_gliner_inputs(text, entity_types)
    outputs = gliner_session.run(None, inputs)
    entities = parse_gliner_outputs(outputs, text, entity_types)
    return [{"type": e["type"], "value": e["text"], "score": e["score"]}
            for e in entities if e["score"] > 0.7]
```

### Шаг 4: Векторизация (~12ms EmbeddingGemma)

Векторизируем сжатое представление (brief + теги), не raw text.
Быстрее, точнее, экономит контекстный бюджет при retrieval.

### Шаг 5: Расчёт Score

```python
import math, time

def calculate_score(relevance, created_at, importance, config):
    age_days = (time.time() - created_at) / 86400
    T = math.exp(-config["temporal_decay_lambda"] * age_days)
    I = config["importance_levels"][importance]
    w = config["score_weights"]
    return w["relevance"] * relevance + w["temporal"] * T + w["importance"] * I

# v1.3: importance_levels расширены
IMPORTANCE_LEVELS = {
    "background": 0.1,
    "important":  0.5,
    "critical":   1.0,
    "principle":  1.0,   # NEW v1.3: принципы = max вес
}
```

### Шаг 6: Сохранение (~1ms RAM, async SQLite)

> **v1.3:** при urgency≠none создаётся deadline anchor и urgency_index запись.

```python
import asyncio

async def save_to_session_index(entity, ram_index, hnsw_index,
                                urgency_index, db_conn):
    sid = entity["session_id"]
    ram_index[sid] = {
        "tags":       entity["tags"],
        "brief":      entity["brief"][:50],
        "importance": entity["importance"],
        "anchors":    entity["anchors"],
        "score":      entity["score"],
        "age_signal": "fresh",
        "updated_at": int(time.time()),
        # NEW v1.3:
        "urgency":         entity.get("urgency", "none"),
        "deadline_ts":     entity.get("deadline_ts"),
        "urgency_active":  entity.get("urgency", "none") != "none",
        "urgency_expired": False,
    }

    # NEW v1.3: обновить urgency_index
    if entity.get("urgency", "none") != "none" and entity.get("deadline_ts"):
        urgency_index[sid] = build_urgency_item(sid, ram_index[sid])

    hnsw_index.add_items([entity["embedding"]], [hash(sid) % 2**31])
    asyncio.create_task(flush_to_sqlite(entity, db_conn))
```

---

## 3. Когда NER, когда детерминированный

```
Весь output агента
        |
        v
Детерминированный фильтр  (+detect_urgency, +detect_principle  v1.3)
        |
        |-> urgency != "none":
        |     -> создать anchor {type="deadline", value=deadline_val}
        |     -> urgency_index[session_id] = UrgencyItem(...)
        |
        |-> importance == "principle":
        |     -> прямо в Session Index (без NER, экономим 8ms)
        |     -> evict_policy = NEVER (Dissolver не трогает)
        |
        |-> precision_items обнаружены:
        |     -> Precision Log немедленно (без NER)
        |
        |-> importance == "critical" И entities ясны:
        |     -> прямо в Session Index (без NER)
        |
        |-> importance == "background":
        |     -> пропустить
        |
        -> importance "important" ИЛИ сложные сущности:
              -> GLiNER NER -> Session Index

Результат: ~70% фрагментов без NER, GLiNER только ~30% случаев.
```

---

## 4. Offline Consolidation (паттерн LightMem ICLR 2026)

Фоновый worker каждые 5 минут:

```python
async def consolidation_worker(ram_index, urgency_index, db_conn):
    while True:
        await asyncio.sleep(300)

        # 1. Пересчитать Score для всех сессий в RAM
        for sid, data in ram_index.items():
            data["score"] = calculate_score(
                data.get("last_relevance", 0.5),
                data["created_at"], data["importance"], CONFIG
            )

        # 2. Обновить age_signal
        now = time.time()
        for sid, data in ram_index.items():
            age = (now - data["created_at"]) / 86400
            if age > 90:  data["age_signal"] = "archive"
            elif age > 30: data["age_signal"] = "stale"
            elif age > 7:  data["age_signal"] = "actual"

        # 3. NEW v1.3: проверить истёкшие дедлайны
        for sid, item in list(urgency_index.items()):
            if not item.expired and item.deadline_ts < now:
                ram_index[sid]["urgency_expired"] = True
                ram_index[sid]["urgency_active"]  = False
                urgency_index[sid].expired = True
                # Dissolver: compress_to_bare_entity()
                asyncio.create_task(compress_to_bare_entity(sid, ram_index))

        # 4. Evict если RAM > 80%
        # NEW v1.3: can_evict() проверяет principle и urgency_active
        if len(ram_index) > CONFIG["session_window_size"] * 0.8:
            await evict_oldest_sessions(ram_index)

        # 5. Batch flush в SQLite
        await batch_flush_to_sqlite(pending_updates)
```

---

## 5. Классификация типа сессии

Observer определяет тип сессии в первые 3-5 обменов:

```python
SESSION_TYPE_SIGNALS = {
    "content":  ["напиши","создай","реализуй","код","функция","глава","сцена"],
    "research": ["найди","исследуй","проанализируй","сравни","как работает"],
    "context":  ["решили","архитектура","план","проблема","требование"],
}

def classify_session_type(text: str) -> str:
    scores = {t: sum(1 for s in sigs if s in text.lower())
              for t, sigs in SESSION_TYPE_SIGNALS.items()}
    return max(scores, key=scores.get)
```

Тип определяет стратегию хранения:
- `content`  → агент активирует контентную ветку
- `research` → Observer агрессивнее сохраняет прецизионные данные
- `context`  → Observer агрессивнее сохраняет решения и якоря

---

## 6. Метрики Observer

```python
observer_metrics = {
    "total_processed":      0,
    "deterministic_only":   0,    # цель: > 70%
    "ner_required":         0,
    "precision_extracted":  0,
    "avg_latency_ms":       0.0,  # цель: < 25ms
    "ram_index_size":       0,
    "evictions_today":      0,
    "sqlite_pending":       0,
    # NEW v1.3:
    "urgency_detected":     0,    # записей с urgency≠none
    "principles_detected":  0,    # записей с importance=principle
    "urgency_expired_today":0,    # истекло за сегодня
}
```

---

## Изменения v1.3 (патч)

| Что | Где | Overhead |
|---|---|---|
| `detect_urgency()` в шаге [2] | `deterministic_filter()` | +0.1ms regex |
| `detect_principle()` в шаге [2] | `deterministic_filter()` | +0.05ms |
| `importance=principle` в `IMPORTANCE_LEVELS` | шаг [5] Score | 0ms |
| urgency поля в `save_to_session_index()` | шаг [6] | 0ms |
| `urgency_index` обновление | шаг [6] | 0ms |
| Проверка expired дедлайнов | Consolidation Worker | 0ms |
| Новые метрики | `observer_metrics` | 0ms |

*RAM-First Context System | observer_specification v1.3 | 2026-03-06*
