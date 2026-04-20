# Dissolver — Спецификация
## RAM-First Context System v1.3
## Патч: urgency_policy | Дата: 2026-03-06

> **Изменения v1.3:** добавлены `compress_to_bare_entity()`, `dissolver_urgency_check()`,
> обновлены `recalc()` (lambda для principle), `decide_eviction()` (NEVER для principle
> и urgency_active). Остальные разделы без изменений относительно v1.1.

---

## 1. Роль и философия

Dissolver — механизм управления **плотностью памяти**, не сборщик мусора.
Он не решает "удалить или нет" — он решает "насколько подробно помнить".

Каждая сессия имеет коэффициент `resolution` от 0.05 до 1.0:
- `1.0` — полная детализация, всё в RAM
- `0.05` — только embedding, данные в SQLite Eternal

**Ключевые принципы:**
- Embedding НИКОГДА не удаляется — HNSWlib хранит вечно
- `is_milestone=true` → `resolution >= 0.05` всегда, `original_brief` заморожен
- `importance=principle` → `evict_policy=NEVER` (NEW v1.3)
- `urgency_active=true` → `evict_policy=NEVER` до истечения срока (NEW v1.3)
- `conflict_flag=true` → dissolution приостановлена до разрешения конфликта
- `ctx.semantic()` работает по ВСЕМ слоям одинаково (через HNSWlib)

---

## 2. Три точки встройки

Dissolver не отдельный процесс — три точки в существующих механизмах:

```
Observer (async coroutine)
    └── при каждом ctx.save() новой сессии
            └── Dissolver.recalc() для сессий с теми же тегами

Consolidation Worker (каждые 300 сек)
    └── Dissolver.batch_recalc() всех сессий в RAM
    └── Dissolver.urgency_check()   NEW v1.3

ctx.get() / ctx.semantic() / ctx.search()
    └── Dissolver.touch(session_id) → use_count++
```

---

## 3. Поля SQLite на которые опирается

```python
# Ось 1: Время
created_at        # INT unix timestamp
updated_at        # INT unix timestamp

# Ось 2: Использование
use_count         # INT
use_history       # JSON [timestamp, ...]

# Ось 3: Прогрессивный контекст
successors        # INT

# Защитные флаги
is_milestone      # BOOL
importance        # TEXT — background/important/critical/principle (NEW v1.3)
conflict_flag     # BOOL
layer             # TEXT
resolution        # REAL

# NEW v1.3:
urgency           # TEXT — none/deadline_h/deadline_d/deadline_w
deadline_ts       # INT  — unix timestamp дедлайна
urgency_active    # BOOL — True пока дедлайн не истёк
urgency_expired   # BOOL — True после истечения
bare_entity       # BOOL — True после compress_to_bare_entity
```

---

## 4. Формула recalc (обновлена v1.3)

```python
import math, time

def recalc(session: dict, config: dict) -> float:

    now = time.time()

    # Ось 1: Время
    age_years = (now - session["created_at"]) / (365 * 86400)
    lambda_map = {
        "critical":   0.05,
        "important":  0.15,
        "background": 0.40,
        "principle":  0.00,   # NEW v1.3: принципы НЕ распадаются со временем
    }
    lam = lambda_map.get(session["importance"], 0.15)
    time_factor = math.exp(-lam * age_years)

    # Ось 2: Использование
    uses_per_year = session["use_count"] / max(age_years, 0.01)
    use_factor = 1 + 0.8 * math.log(1 + uses_per_year)

    # Ось 3: Прогрессивный контекст
    prog_factor = 1.0 - (0.3 * min(session["successors"], 10) / 10)

    resolution = time_factor * use_factor * prog_factor

    # Защита milestone
    if session.get("is_milestone"):
        resolution = max(resolution, 0.05)

    # NEW v1.3: principle — resolution не падает ниже 0.8 (всегда RAM Hot/Warm)
    if session.get("importance") == "principle":
        resolution = max(resolution, 0.80)

    # Пауза при конфликте
    if session.get("conflict_flag"):
        return session["resolution"]

    # Защита: молодое critical не трогаем
    age_days = age_years * 365
    if session["importance"] == "critical" and age_days < 30:
        return session["resolution"]

    return min(resolution, 1.0)
```

---

## 5. Триггеры включения и паузы

### Включение
| Триггер | Откуда | Действие |
|---|---|---|
| Observer сохранил новую сессию | `ctx.save()` | `successors++` у предков → `recalc` |
| Агент прочитал сессию | `ctx.get()`, `ctx.semantic()` | `touch()` → `use_count++` |
| Consolidation Worker | каждые 300s | `batch_recalc()` + `urgency_check()` |
| RAM > soft_limit (380MB) | eviction check | `recalc` + принудительный сдвиг слоя |
| RAM > hard_limit (480MB) | экстренно | агрессивный evict немедленно |

### Пауза / заморозка
```python
if session["conflict_flag"]:                    return session["resolution"]
if session["is_milestone"]:                     resolution = max(resolution, 0.05)
if session["importance"] == "principle":        resolution = max(resolution, 0.80)  # NEW
if session.get("urgency_active"):               # NEW: не двигаем слой
    return max(session["resolution"], 0.80)     # держим в RAM Hot пока active
if importance == "critical" and age_days < 30:  return session["resolution"]
```

---

## 6. Пять слоёв — таблица

| resolution | Слой | Что в RAM | Что в SQLite |
|---|---|---|---|
| > 0.8 | RAM Hot | brief + why_log + precision + anchors + embedding | всё дублируется async |
| 0.5–0.8 | RAM Warm | brief + tags + anchors | precision → SQLite |
| 0.3–0.5 | SQLite Deep | — evicted — | brief(20) + tags(2) + embedding |
| 0.1–0.3 | SQLite Archive | — evicted — | brief(20) + embedding |
| ≤ 0.05 | SQLite Eternal | — evicted — | embedding only |

> **principle:** всегда RAM Hot/Warm (resolution ≥ 0.80), никогда не вытесняется.
> **urgency_active:** всегда RAM Hot (resolution = 1.0) пока дедлайн активен.

HNSWlib Session хранит ВСЕ векторы независимо от слоя.

---

## 7. apply_layer — смена слоя

```python
def apply_layer(session_id: str, new_resolution: float,
                ram_index: dict, db_conn):

    def resolution_to_layer(r: float) -> str:
        if r > 0.8:  return "RAM_HOT"
        if r > 0.5:  return "RAM_WARM"
        if r > 0.3:  return "SQLite_Deep"
        if r > 0.1:  return "SQLite_Archive"
        return "SQLite_Eternal"

    old_layer = ram_index.get(session_id, {}).get("layer", "RAM_HOT")
    new_layer = resolution_to_layer(new_resolution)

    if new_layer == old_layer:
        if session_id in ram_index:
            ram_index[session_id]["resolution"] = new_resolution
        return

    if new_layer == "RAM_WARM":
        flush_precision_to_sqlite(session_id, db_conn)
        ram_index[session_id]["layer"] = "RAM_WARM"
    elif new_layer == "SQLite_Deep":
        evict_to_sqlite(session_id, keep="brief20_tags2_emb", db_conn=db_conn)
        del ram_index[session_id]
    elif new_layer == "SQLite_Archive":
        truncate_sqlite_record(session_id, keep="brief20_emb", db_conn=db_conn)
    elif new_layer == "SQLite_Eternal":
        truncate_sqlite_record(session_id, keep="emb_only", db_conn=db_conn)
```

---

## 8. Eviction Policy (обновлена v1.3)

```python
EVICTION_CONFIG = {
    "ram_hard_limit_mb": 480,
    "ram_soft_limit_mb": 380,
    "window_default":    200,
    "window_min":         50,
}

def decide_eviction(ram_index: dict) -> list:
    scored = sorted(ram_index.items(), key=lambda x: x[1]["score"])

    candidates = []
    for sid, data in scored:
        if data.get("conflict_flag"):                          continue
        if data.get("is_milestone"):                           continue
        if data.get("importance") == "principle":             continue  # NEW v1.3
        if data.get("urgency_active"):                        continue  # NEW v1.3
        if (data["importance"] == "critical"
                and data["age_signal"] == "fresh"):           continue
        candidates.append(sid)

    return candidates
```

---

## 9. NEW v1.3: compress_to_bare_entity()

```python
async def compress_to_bare_entity(session_id: str, ram_index: dict,
                                   db_conn=None) -> None:
    """
    Вызывается Dissolver после истечения urgency дедлайна.
    Q-I запись: full ~2KB → bare ~200 bytes.
    principle: НЕ сжимаем (детали важны долго).

    Жизненный цикл Q-I:
        T+0:   full, importance=critical, urgency=deadline_d, RAM Hot
        T+Nd:  дедлайн истёк → compress_to_bare_entity()
        T+30d: SQLite Warm
        T+1y:  SQLite Deep
        T+10y: голый факт навсегда (исторический архив)
    """
    data = ram_index.get(session_id, {})
    if not data:
        return
    if data.get("importance") == "principle":
        return  # принципы НЕ сжимаем

    ram_index[session_id] = {
        **data,
        "value":           data.get("brief", "")[:50],
        "tags":            data.get("tags", [])[:3],
        "importance":      data.get("importance", "background"),
        "created_at":      data.get("created_at"),
        "urgency_expired": True,
        "urgency_active":  False,
        "status":          "bare",
        "bare_entity":     True,
        "brief_full":      None,   # детали удалены
        "context":         None,
        # embedding: не трогаем, HNSWlib держит вечно
    }
    # async flush → SQLite WAL
    if db_conn:
        asyncio.create_task(flush_bare_entity(session_id, db_conn))
```

---

## 10. NEW v1.3: dissolver_urgency_check()

```python
def dissolver_urgency_check(
    ram_index: dict,
    urgency_index: dict,
    db_conn=None,
) -> list:
    """
    Вызывается Consolidation Worker каждые 5 минут.
    Находит все записи где deadline_ts < now и expired=False.
    Помечает как expired + запускает compress_to_bare_entity().
    Возвращает список session_id помеченных в этом проходе.
    """
    now = time.time()
    newly_expired = []

    for sid, item in list(urgency_index.items()):
        if item.expired:
            continue
        if item.deadline_ts < now:
            # Пометить expired
            if sid in ram_index:
                ram_index[sid]["urgency_expired"] = True
                ram_index[sid]["urgency_active"]  = False
            urgency_index[sid].expired = True
            # Запустить сжатие
            asyncio.create_task(compress_to_bare_entity(sid, ram_index, db_conn))
            newly_expired.append(sid)

    return newly_expired
```

---

## 11. Холодный старт — Dissolver при bootstrap

```
1. Открыть SQLite
2. Загрузить ВСЕ embeddings → перестроить Session HNSWlib
3. Загрузить последние N сессий в RAM по Score
4. Для каждой загруженной: recalc(session) → apply_layer()
5. NEW v1.3: восстановить urgency_index из sessions WHERE urgency_active=1
6. Сессии ниже RAM_WARM в RAM не грузить (только HNSWlib + SQLite)
```

```python
def bootstrap_urgency_index(db_conn, ram_index) -> dict:
    """Восстановить urgency_index из SQLite при холодном старте."""
    urgency_index = {}
    rows = db_conn.execute(
        "SELECT session_id FROM sessions WHERE urgency_active=1"
    ).fetchall()
    for (sid,) in rows:
        data = ram_index.get(sid) or sqlite_load(sid, db_conn)
        if data:
            item = build_urgency_item(sid, data)
            if item:
                urgency_index[sid] = item
    return urgency_index
```

---

## 12. Growth Budget — давление диска

```python
CONFIG["db_growth_budget_mb_per_day"] = 2.0

def growth_pressure_factor(actual_growth_mb: float) -> float:
    budget = CONFIG["db_growth_budget_mb_per_day"]
    if actual_growth_mb <= budget:
        return 1.0
    return budget / actual_growth_mb  # < 1.0 → ускоряем dissolution
```

---

## 13. Временные горизонты

| Тип | 1 год | 5 лет | 20 лет | Слой финальный |
|---|---|---|---|---|
| `principle` | RAM Warm | RAM Warm | RAM Warm | RAM Warm (≥0.80 всегда) |
| `critical` (Q-I) | bare (после expired) | SQLite Deep | SQLite Eternal | — |
| `important` | RAM Hot | SQLite Deep | SQLite Eternal | — |
| `background` | SQLite Archive | SQLite Eternal | — | — |

---

## Изменения v1.3 (патч)

| Что | Где | Приоритет |
|---|---|---|
| `importance=principle` в `lambda_map` = 0.0 | `recalc()` | P0 |
| `resolution >= 0.80` для `principle` | `recalc()` | P0 |
| `urgency_active` → resolution = 1.0 (RAM Hot) | `recalc()` | P0 |
| `evict_policy=NEVER` для `principle` | `decide_eviction()` | P0 |
| `evict_policy=NEVER` для `urgency_active` | `decide_eviction()` | P0 |
| `urgency_active/expired` поля в SQLite schema | `поля` | P0 |
| `compress_to_bare_entity()` | новый метод | P1 |
| `dissolver_urgency_check()` | новый метод | P1 |
| `bootstrap_urgency_index()` | bootstrap | P0 |
| Точка встройки в Consolidation Worker | `urgency_check()` | P1 |

*RAM-First Context System | dissolver_specification v1.3 | 2026-03-06*
