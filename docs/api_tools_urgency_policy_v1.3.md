# API Tools Specification v1.3

# RAM-First Context System

# urgency_policy — полный раздел

# Статус: ЗАФИКСИРОВАНО | Дата: 2026-03-06

# Дополняет: api_tools_specification_v2.md (v1.1)

---

## Содержание

1. [Принципы urgency_policy](#1-принципы-urgency_policy)
2. [Новые типы данных](#2-новые-типы-данных)
3. [Обновлённые схемы](#3-обновлённые-схемы)
4. [Уровень 1 — тихое поведение](#4-уровень-1--тихое-поведение)
5. [Уровень 2 — явные параметры](#5-уровень-2--явные-параметры)
6. [Уровень 3 — агрегаторы P2](#6-уровень-3--агрегаторы-p2)
7. [Observer — детекторы urgency и principle](#7-observer--детекторы)
8. [Dissolver — urgency_check и compress_to_bare_entity](#8-dissolver)
9. [SQLite schema — изменения](#9-sqlite-schema)
10. [Сводная таблица изменений](#10-сводная-таблица)

---

## 1. Принципы urgency_policy

`importance` и `urgency` — **два независимых измерения**. Смешивать нельзя.

| Параметр     | Определяет                        | Тип                                             |
| ------------ | --------------------------------- | ----------------------------------------------- |
| `importance` | КАК ДОЛГО хранить (долговечность) | `background / important / critical / principle` |
| `urgency`    | КОГДА нужно действовать (дедлайн) | `none / deadline_h / deadline_d / deadline_w`   |

### Матрица квадрантов (Эйзенхауэр для памяти)

```
                  СРОЧНОЕ (urgency≠none)    НЕ СРОЧНОЕ (urgency=none)
            ┌──────────────────────────┬────────────────────────────┐
  ВАЖНОЕ    │  Q-I: Кризис/дедлайн    │  Q-II: Принципы/решения    │
            │  Жизнь: 1–7 дней        │  Жизнь: годами             │
            │  importance=critical     │  importance=principle      │
            │  Decay: быстрый после   │  Decay: ~0 (голая сущность)│
            ├──────────────────────────┼────────────────────────────┤
  НЕ ВАЖНОЕ │  Q-III: Псевдосрочное   │  Q-IV: Фоновое             │
            │  Жизнь: часы            │  importance=background     │
            └──────────────────────────┴────────────────────────────┘
```

### Три уровня urgency-awareness в инструментах

| Уровень           | Принцип                        | Инструменты                               |
| ----------------- | ------------------------------ | ----------------------------------------- |
| **1 — ТИХИЙ**     | Автоматически, агент не думает | `ctx.bridge`, `ctx.semantic`, `ctx.evict` |
| **2 — ЯВНЫЙ**     | Опциональные параметры         | `ctx.search`, `ctx.anchors`, `ctx.get`    |
| **3 — АГРЕГАТОР** | P2, convenience API            | `ctx.urgent`, `ctx.expire`                |

---

## 2. Новые типы данных

```python
from typing import Literal, Optional
from dataclasses import dataclass, field

# ImportanceLevel — ОБНОВЛЁН: добавлен principle (заменяет PRIORITY)
ImportanceLevel = Literal["background", "important", "critical", "principle"]
# principle: пользователь явно указал ("никогда", "всегда", "non-negotiable")
# critical:  система определила как важное

# UrgencyLevel — НОВЫЙ
UrgencyLevel = Literal["none", "deadline_h", "deadline_d", "deadline_w"]
# deadline_h: срок в часах
# deadline_d: срок в днях
# deadline_w: срок в неделях
# none:       без дедлайна

# UrgencyItem — НОВЫЙ (для urgency_index и ctx.urgent)
@dataclass
class UrgencyItem:
    value:       str             # "демо клиенту"
    session_id:  str
    deadline_ts: int             # unix timestamp
    hours_left:  float           # < 0 если уже истёк
    urgency:     str             # UrgencyLevel
    importance:  str             # ImportanceLevel
    tags:        list[str]
    expired:     bool = False    # True если deadline_ts < now
```

---

## 3. Обновлённые схемы

### SessionBrief — +3 поля (P0)

```python
@dataclass
class SessionBrief:
    # --- существующие поля (v1.0) ---
    session_id:      str
    tags:            list[str]
    brief:           str                   # max 50 chars
    importance:      str                   # ImportanceLevel
    age_signal:      str                   # fresh/actual/stale/archive
    score:           float
    anchors:         list[dict]
    conflict:        bool
    # --- НОВЫЕ ПОЛЯ v1.3 ---
    urgency:         str           = "none"   # UrgencyLevel
    deadline_ts:     Optional[int] = None     # None если urgency=none
    urgency_expired: bool          = False    # True если срок истёк
```

### SessionBridge — +1 поле (P0, критично)

```python
@dataclass
class SessionBridge:
    # --- существующие поля (v1.0) ---
    context_brief:    str
    intent_summary:   str
    active_variables: list[str]           # max 9
    open_issues:      list[str]
    last_decisions:   list[str]
    precision_items:  list[dict]
    next_action:      Optional[str]
    # --- НОВОЕ ПОЛЕ v1.3 ---
    urgency_active:   list[UrgencyItem] = field(default_factory=list)
    # Заполняется АВТОМАТИЧЕСКИ при каждом ctx.bridge()
    # Все UrgencyItem где expired=False, сортировка по hours_left asc
    # Latency: 0ms (urgency_index в RAM)
```

### Anchor — +2 поля (P0)

```python
@dataclass
class Anchor:
    # --- существующие поля (v1.0) ---
    type:          str   # decision/phone/address/person/number/date/deadline
    value:         str
    context_tag:   str
    session_id:    str
    importance:    str
    created_at:    int
    # --- НОВЫЕ ПОЛЯ v1.3 ---
    urgency_status: str            = "none"  # "active" | "expired" | "none"
    deadline_ts:    Optional[int]  = None
```

---

## 4. Уровень 1 — тихое поведение

Агент не передаёт дополнительных параметров — инструменты работают правильно сами.

### ctx.bridge() — urgency_active[] автоматически

```python
def ctx_bridge(ram_index: dict, urgency_index: dict) -> SessionBridge:
    """
    ИЗМЕНЕНИЕ v1.3: urgency_active[] заполняется при каждом вызове.
    Агент видит все активные дедлайны при старте сессии.
    Latency: <0.01ms (urgency_index RAM dict lookup)
    """
    active = sorted(
        [item for item in urgency_index.values() if not item.expired],
        key=lambda x: x.hours_left  # самые срочные первыми
    )
    bridge = _build_bridge_from_ram(ram_index)  # существующая логика
    bridge.urgency_active = active
    return bridge
```

### ctx.semantic() — score модификаторы

```python
URGENCY_EXPIRED_PENALTY = 0.50   # Q-I expired  → score × 0.50 (топится вниз)
PRINCIPLE_BOOST         = 1.30   # Q-II принципы → score × 1.30 (поднимается)

def apply_urgency_score_modifier(score: float, session_data: dict) -> float:
    """Вызывается в Score финальном [28] ctx.semantic(). Тихий, агент не видит."""
    if session_data.get("urgency_expired"):
        score *= URGENCY_EXPIRED_PENALTY
    if session_data.get("importance") == "principle":
        score *= PRINCIPLE_BOOST
    return score
```

### ctx.evict() — защита principle и urgency_active

```python
def can_evict(session_data: dict) -> bool:
    """
    evict_policy=NEVER для:
      - importance=principle  (принципы не вытесняются никогда)
      - urgency_active=True   (активный дедлайн — не вытесняем до истечения)
    """
    if session_data.get("importance") == "principle":
        return False
    if session_data.get("urgency_active"):
        return False
    return True
```

---

## 5. Уровень 2 — явные параметры

Опциональные параметры. Агент использует когда нужна точная фильтрация.

### ctx.search() — новый параметр urgency=

```python
def ctx_search(
    ram_index: dict,
    tags: list[str],
    importance: Optional[str] = None,
    age: Optional[str] = None,
    limit: int = 10,
    urgency: Optional[Literal["active", "expired"]] = None,  # НОВЫЙ v1.3
) -> list[SessionBrief]:
    """
    urgency="active"  → только Q-I с активными дедлайнами
    urgency="expired" → только Q-I с истёкшими (исторический анализ)
    urgency=None      → поведение v1.0 (дефолт, совместимость)
    Latency: ~0.1ms RAM dict

    Пример:
        ctx.search(tags=["#auth"], urgency="active")
        → только сессии с активным дедлайном и тегом #auth
    """
    results = _tag_filter(ram_index, tags, importance, age, limit)
    if urgency == "active":
        results = [r for r in results
                   if r.urgency != "none" and not r.urgency_expired]
    elif urgency == "expired":
        results = [r for r in results if r.urgency_expired]
    return results
```

### ctx.anchors() — новый параметр urgency_status=

```python
def ctx_anchors(
    ram_index: dict,
    anchor_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 20,
    urgency_status: Optional[Literal["active", "expired"]] = None,  # НОВЫЙ v1.3
) -> list[Anchor]:
    """
    urgency_status="active"  → только живые дедлайны
    urgency_status="expired" → только истёкшие
    urgency_status=None      → все (дефолт)

    Пример:
        ctx.anchors(anchor_type="deadline", urgency_status="active")
        → все активные дедлайны проекта
    Latency: ~0.1ms RAM dict
    """
    anchors = _get_anchors(ram_index, anchor_type, session_id, limit)
    if urgency_status == "active":
        anchors = [a for a in anchors if a.urgency_status == "active"]
    elif urgency_status == "expired":
        anchors = [a for a in anchors if a.urgency_status == "expired"]
    return anchors
```

### ctx.get() — +3 поля в ответе

```python
def ctx_get(session_id: str, ram_index: dict) -> SessionBrief:
    """
    ИЗМЕНЕНИЕ v1.3: возвращает urgency, deadline_ts, urgency_expired.
    Агент получает если есть, игнорирует если нет.
    Latency: <0.01ms RAM dict
    """
    data = ram_index.get(session_id, {})
    return SessionBrief(
        # ... существующие поля ...
        urgency=data.get("urgency", "none"),             # NEW
        deadline_ts=data.get("deadline_ts"),             # NEW
        urgency_expired=data.get("urgency_expired", False),  # NEW
    )
```

---

## 6. Уровень 3 — агрегаторы P2

Удобный API. Реализовать после P0 и P1. `ctx.bridge()` закрывает 90% случаев.

### ctx.urgent() — НОВЫЙ инструмент

```python
def ctx_urgent(
    urgency_index: dict,
    hours_ahead: float = 72.0,
) -> list[UrgencyItem]:
    """
    Возвращает все активные срочные записи в ближайшие hours_ahead часов.
    Сортировка: hours_left asc (самые срочные первыми).

    Latency: <0.1ms (urgency_index RAM dict)
    RAM:     urgency_index ~1MB (в SystemContext)

    Когда нужен:
        Агент явно планирует: "дай все дедлайны ближайших 3 дней"
    Когда НЕ нужен:
        Обычная работа — ctx.bridge() уже показал urgency_active[]

    Пример:
        items = ctx.urgent(hours_ahead=48)
        # → [UrgencyItem(value="демо клиенту", hours_left=6.0, ...),
        #    UrgencyItem(value="RS256 аудит",  hours_left=31.2, ...)]
    """
    now = time.time()
    cutoff = now + hours_ahead * 3600
    return sorted(
        [i for i in urgency_index.values()
         if not i.expired and i.deadline_ts <= cutoff],
        key=lambda x: x.hours_left
    )
```

### ctx.expire() — НОВЫЙ инструмент

```python
def ctx_expire(
    session_id: str,
    ram_index: dict,
    urgency_index: dict,
    db=None,
) -> None:
    """
    Явно помечает urgency как expired.
    Вызывается: Dissolver автоматически (каждые 5 мин)
                или агентом вручную ("дедлайн прошёл, отметь")

    Эффект:
        ram_index[session_id]["urgency_expired"] = True
        ram_index[session_id]["urgency_active"]  = False
        urgency_index[session_id].expired        = True
        Dissolver → compress_to_bare_entity() для Q-I записей

    Latency: <0.01ms RAM + async SQLite flush
    """
    if session_id in ram_index:
        ram_index[session_id]["urgency_expired"] = True
        ram_index[session_id]["urgency_active"]  = False
    if session_id in urgency_index:
        urgency_index[session_id].expired = True
    # asyncio.create_task(flush_urgency_expired(session_id, db))
```

---

## 7. Observer — детекторы

### Сигналы urgency (детерм. фильтр, шаг [2])

```python
URGENCY_SIGNALS = {
    "deadline_h": [
        "через час", "через два часа", "в течение часа",
        "in 1 hour", "in 2 hours", "asap", "срочно сейчас",
    ],
    "deadline_d": [
        "сегодня", "завтра", "today", "tomorrow",
        "до конца дня", "by eod", "дедлайн сегодня", "deadline today",
    ],
    "deadline_w": [
        "на этой неделе", "до конца недели", "this week",
        "by friday", "до пятницы", "через неделю", "in a week",
    ],
}

PRINCIPLE_SIGNALS = [
    "никогда", "всегда", "запомни это", "это принцип",
    "правило проекта", "архитектурное решение",
    "never", "always", "remember this", "non-negotiable",
    "project rule", "architectural principle",
]

DEADLINE_PATTERN = re.compile(
    r'\b(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?'
    r'|\d{4}-\d{2}-\d{2}'
    r'|(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]* \d{1,2})\b',
    re.IGNORECASE
)
```

### detect_urgency()

```python
def detect_urgency(text: str) -> tuple[str, Optional[str]]:
    """
    Возвращает (UrgencyLevel, deadline_value_str | None).
    Latency: ~0.1ms (regex, шаг [2] Observer)
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
```

### detect_principle()

```python
def detect_principle(text: str) -> bool:
    """
    True → importance=principle вместо critical/important.
    Пользователь явно указал принцип: "никогда", "always", "non-negotiable"...
    Latency: ~0.05ms (in operator)
    """
    t = text.lower()
    return any(sig in t for sig in PRINCIPLE_SIGNALS)
```

### Интеграция в Observer pipeline

```
[2] Детерм. фильтр:
    urgency, deadline_val = detect_urgency(text)
    is_principle = detect_principle(text)
    if is_principle: importance = "principle"
    if urgency != "none":
        → добавить anchor: {type="deadline", value=deadline_val, deadline_ts=...}
        → session["urgency"] = urgency
        → session["urgency_active"] = True
        → urgency_index[session_id] = build_urgency_item(session_id, session)
```

---

## 8. Dissolver

### dissolver_urgency_check() — каждые 5 минут

```python
def dissolver_urgency_check(
    ram_index: dict,
    urgency_index: dict,
    db=None,
) -> list[str]:
    """
    Вызывается Consolidation Worker каждые 5 минут.
    Проверяет истекшие дедлайны → запускает compress_to_bare_entity().
    Возвращает список session_id которые были помечены expired.
    """
    now = time.time()
    expired_ids = []
    for sid, item in list(urgency_index.items()):
        if not item.expired and item.deadline_ts < now:
            ctx_expire(sid, ram_index, urgency_index, db)
            compress_to_bare_entity(sid, ram_index)
            expired_ids.append(sid)
    return expired_ids
```

### compress_to_bare_entity() — Q-I после истечения

```python
def compress_to_bare_entity(session_id: str, ram_index: dict) -> None:
    """
    После истечения дедлайна: сжимаем Q-I запись.
    Q-I: full ~2KB → bare ~200 bytes
    Q-II (principle): НЕ сжимаем — детали важны долго

    Жизненный цикл:
        T+0:   full запись, importance=critical, urgency=deadline_d
        T+Nd:  дедлайн истёк → compress_to_bare_entity()
        T+30d: SQLite Warm (~200 bytes)
        T+1y:  SQLite Deep (~50 bytes)
        T+10y: голый факт навсегда (исторический архив)
    """
    data = ram_index.get(session_id, {})
    if data.get("importance") == "principle":
        return  # принципы НЕ сжимаем
    bare = {
        "value":           data.get("brief", "")[:50],
        "tags":            data.get("tags", [])[:3],  # только топ-3 тега
        "importance":      data.get("importance", "background"),
        "created_at":      data.get("created_at"),
        "urgency_expired": True,
        "status":          "bare",
        "brief_full":      None,   # детали удалены
        "context":         None,   # контекст удалён
        # embedding: пересчитывается при необходимости
    }
    ram_index[session_id] = {**ram_index.get(session_id, {}), **bare}
    # async flush → SQLite WAL
```

---

## 9. SQLite schema

```sql
-- sessions таблица (v1.0 → v1.3)
ALTER TABLE sessions ADD COLUMN urgency          TEXT    DEFAULT 'none';
ALTER TABLE sessions ADD COLUMN deadline_ts      INTEGER;
ALTER TABLE sessions ADD COLUMN urgency_active   INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN urgency_expired  INTEGER DEFAULT 0;
ALTER TABLE sessions ADD COLUMN bare_entity      INTEGER DEFAULT 0;

-- anchors таблица (v1.0 → v1.3)
ALTER TABLE anchors  ADD COLUMN urgency_status   TEXT    DEFAULT 'none';
ALTER TABLE anchors  ADD COLUMN deadline_ts      INTEGER;

-- Новые индексы
CREATE INDEX idx_sessions_urgency   ON sessions(urgency_active, deadline_ts)
  WHERE urgency_active = 1;

CREATE INDEX idx_sessions_principle ON sessions(importance)
  WHERE importance = 'principle';
```

---

## 10. Сводная таблица изменений

| Изменение                                 | Уровень     | RAM      | Latency     | Приоритет |
| ----------------------------------------- | ----------- | -------- | ----------- | --------- |
| `SessionBrief` +3 поля                    | схема       | 0MB      | 0ms         | **P0**    |
| `SessionBridge urgency_active[]`          | 1 тихий     | 0MB      | 0ms         | **P0**    |
| `Anchor` +2 поля                          | схема       | 0MB      | 0ms         | **P0**    |
| `evict_policy=NEVER` для `principle`      | 1 тихий     | 0MB      | 0ms         | **P0**    |
| `evict_policy=NEVER` для `urgency_active` | 1 тихий     | 0MB      | 0ms         | **P0**    |
| `urgency_index` в RAM                     | инфра       | ~1MB     | <0.1ms      | **P0**    |
| `Observer detect_urgency`                 | Observer    | 0MB      | +0.1ms      | **P0**    |
| `Observer detect_principle`               | Observer    | 0MB      | +0.05ms     | **P0**    |
| SQLite 5 ALTER + 2 индекса                | SQLite      | 0MB      | one-time    | **P0**    |
| `ctx.get()` +3 поля                       | 2 явный     | 0MB      | 0ms         | **P0**    |
| `semantic score ×0.5/×1.3`                | 1 тихий     | 0MB      | 0ms         | P1        |
| `ctx.search(urgency=)`                    | 2 явный     | 0MB      | 0ms         | P1        |
| `ctx.anchors(urgency_status=)`            | 2 явный     | 0MB      | 0ms         | P1        |
| `Dissolver urgency_check`                 | Dissolver   | 0MB      | 0ms         | P1        |
| `compress_to_bare_entity`                 | Dissolver   | 0MB      | 0ms         | P1        |
| **NEW `ctx.urgent(hours_ahead)`**         | 3 агрегатор | 0MB      | <0.1ms      | P2        |
| **NEW `ctx.expire(session_id)`**          | 3 агрегатор | 0MB      | <0.01ms     | P2        |
| **Итого**                                 |             | **+1MB** | **+0.25ms** |           |

**Инструментов: 16 (v1.1) → 18 (v1.3)**

Новые инструменты: `ctx.urgent()`, `ctx.expire()`  
Формализовать отдельно: `ctx.sync()`, `ctx.load()` (упомянуты в архитектуре)

---

*RAM-First Context System | urgency_policy v1.3 | 2026-03-06*
