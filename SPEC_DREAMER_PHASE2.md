# SPEC: Dreamer Phase 2 — Disk Pattern Search
**Status:** NOT IMPLEMENTED  
**Priority:** P2  
**Last updated:** 2026-04-12  
**Author:** Antigravity (internal)

---

## 1. Контекст и мотивация

`dreamer.py` (165 строк) сейчас работает **только через RAM-слой**:
- `self._ctx.anchor_index.all()` — ограничен `load_anchors(limit=1000)` при bootstrap
- `self._ctx.ram_index` — ограничен `session_window_size` из конфига

**Проблема:** Dreamer не видит сессии, которые вытеснены из RAM dissolver-ом.  
Это нарушает гарантию: `outcome="pending"` может никогда не разрешиться, если связанная сессия находится только на диске.

**Цель Phase 2:** добавить возможность поиска по диску паттернами флагов и маркеров из anchor.flags (JSON) с постепенным расширением окна и сохранением состояния между итерациями.

---

## 2. Scope

### IN SCOPE (Phase 2)
- `DatabaseManager.find_sessions_by_flags()` — SQL через `json_extract` по таблице `sessions`
- `DatabaseManager.find_anchors_by_flags()` — SQL через `json_extract` по таблице `anchors`
- `PersistenceLayer.find_sessions_by_flags()` и `.find_anchors_by_flags()` — тонкие проксирующие методы
- `Dreamer._disk_scan()` — iterative deepening по диску с offset + window
- `Dreamer` state: `_disk_offset`, `_disk_window` между итерациями цикла
- `schemas.py`: индекс `idx_anchors_flags_outcome` по `json_extract(flags, '$.outcome')`
- `check_anchor_schema()`: миграция — добавление индекса если не существует
- Юнит-тесты: `tests/test_dreamer_phase2.py` (≥ 8 тестов)

### OUT OF SCOPE (Phase 3+)
- Constructive Synthesis (centroid group detection) — отдельный спек
- Модификация `_reassess_outcome()` логики — не меняем

---

## 3. Схема данных (анализ текущего состояния)

### 3.1 Таблица anchors
```sql
-- flags хранится как TEXT JSON, поле outcome внутри:
-- '{"outcome": "pending", "user_pin": false, "multi_session": true, ...}'
-- Существующие индексы: anchor_type, decay_level, last_accessed_at, session_id
-- ОТСУТСТВУЕТ: индекс на json_extract(flags, '$.outcome')
```

### 3.2 Таблица sessions
```sql
-- tags: TEXT JSON array, importance: TEXT, urgency: TEXT
-- Существующие индексы: created_at, importance, session_type, urgency_active
-- json_extract через tags поддерживается SQLite 3.38+
```

### 3.3 Anchor dataclass (anchor.py)
```python
flags = {
    "outcome": "pending",       # pending | success | failure | neutral | abandoned
    "multi_session": False,     # bool
    "user_pin": False,          # bool
    "mention_type": "focus",    # focus | passing
    "continuation_of": None,    # session_id или None
    "continuation_depth": 0,
    "is_new_entity": True,
}
```

---

## 4. API: новые методы

### 4.1 `DatabaseManager.find_anchors_by_flags()`

**Файл:** `src/mnemostroma/storage/sqlite.py`

```python
async def find_anchors_by_flags(
    self,
    outcome: Optional[str] = None,
    multi_session: Optional[bool] = None,
    anchor_type: Optional[str] = None,
    decay_level_max: int = 3,
    limit: int = 50,
    offset: int = 0,
) -> list[Anchor]:
    """Query anchors from disk by flag patterns using json_extract.

    Args:
        outcome: Filter by flags.outcome ('pending', 'success', etc.). None = no filter.
        multi_session: Filter by flags.multi_session. None = no filter.
        anchor_type: Filter by anchor_type column. None = no filter.
        decay_level_max: Max decay_level (inclusive). Use 3 to include all.
        limit: Page size.
        offset: Pagination offset for iterative deepening.

    Returns:
        List[Anchor] sorted by last_accessed_at DESC.
    """
```

**SQL pattern:**
```sql
SELECT ... FROM anchors
WHERE
  (? IS NULL OR json_extract(flags, '$.outcome') = ?)
  AND (? IS NULL OR json_extract(flags, '$.multi_session') = ?)
  AND (? IS NULL OR anchor_type = ?)
  AND decay_level <= ?
ORDER BY last_accessed_at DESC
LIMIT ? OFFSET ?
```

> ⚠️ **Хвост #1**: `json_extract` с boolean в SQLite: `True` хранится как JSON `true` (integer 1 в SQLite JSON). Нужно передавать `1` или `0`, не Python `bool`. Тест должен проверить оба варианта.

### 4.2 `DatabaseManager.find_sessions_by_flags()`

**Файл:** `src/mnemostroma/storage/sqlite.py`

```python
async def find_sessions_by_flags(
    self,
    importance: Optional[str] = None,
    urgency: Optional[str] = None,
    has_tag: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[SessionBrief]:
    """Query SessionBriefs from disk by field/tag patterns.

    Uses existing indexed columns. json_extract on tags only if has_tag given.

    Args:
        importance: Filter by importance column. None = no filter.
        urgency: Filter by urgency column ('none','low','medium','high'). None = no filter.
        has_tag: JSON array tag contains this string. Uses json_each() subquery.
        limit: Page size.
        offset: Pagination offset.

    Returns:
        List[SessionBrief] sorted by created_at DESC.
    """
```

> ⚠️ **Хвост #2**: `json_each()` доступен только в SQLite 3.38.0+. Добавить runtime version check при запросе. Если версия ниже — fallback через `tags LIKE '%"<value>"%'` (менее точный, но безопасный). Логировать предупреждение один раз.

### 4.3 `PersistenceLayer.find_anchors_by_flags()` и `.find_sessions_by_flags()`

**Файл:** `src/mnemostroma/storage/persistence.py`

Тонкие proxy-методы в секции `# Point reads — on-demand cold load`:

```python
async def find_anchors_by_flags(self, **kwargs) -> list:
    """Disk search for anchors by flag patterns. See DatabaseManager.find_anchors_by_flags."""
    return await self._db.find_anchors_by_flags(**kwargs)

async def find_sessions_by_flags(self, **kwargs) -> list:
    """Disk search for sessions by field/tag patterns. See DatabaseManager.find_sessions_by_flags."""
    return await self._db.find_sessions_by_flags(**kwargs)
```

---

## 5. Dreamer: Iterative Deepening

### 5.1 Новое состояние (dreamer.py)

```python
class Dreamer:
    def __init__(self, conductor, ctx):
        ...
        # Phase 2 — disk scan state (persistent between dream cycles)
        self._disk_offset: int = 0
        self._disk_window: int = 1000   # starts at 1000, expands up to 6000
```

### 5.2 `_disk_scan()` — новый async метод

```python
async def _disk_scan(self) -> dict:
    """Phase 2: scan disk for anchors missed by RAM layer.

    Strategy: iterative deepening.
    - Per cycle: fetch a page of pending-outcome anchors from SQLite.
    - Attempt _reassess_outcome() for each (already RAM-aware).
    - Advance offset. Reset to 0 when a full pass is complete.
    - Expand window 1000→3000→6000 if 0 resolutions found in a full pass.

    Returns: stats dict.
    """
    if not self._ctx.persistence:
        return {"disk_anchors_checked": 0}

    PAGE_SIZE = 50
    stats = {"disk_anchors_checked": 0, "disk_outcomes_updated": 0}

    anchors = await self._ctx.persistence.find_anchors_by_flags(
        outcome="pending",
        multi_session=True,   # Phase 2 targets multi-session pending only
        decay_level_max=2,    # skip bedrock (decay=3) — already stable
        limit=PAGE_SIZE,
        offset=self._disk_offset,
    )

    if not anchors:
        # Full pass complete — reset and possibly expand window
        was_productive = stats["disk_outcomes_updated"] > 0
        self._disk_offset = 0
        if not was_productive and self._disk_window < 6000:
            self._disk_window = min(self._disk_window * 3, 6000)
            logger.info("dreamer.disk_scan | expanding window to %d", self._disk_window)
        return stats

    for anchor in anchors:
        stats["disk_anchors_checked"] += 1
        # Skip if already in RAM anchor_index (already handled by dream())
        if self._ctx.anchor_index and self._ctx.anchor_index.get(anchor.anchor_id):
            continue
        if self._reassess_outcome(anchor):
            stats["disk_outcomes_updated"] += 1
            anchor.updated_at = int(time.time())
            await self._ctx.persistence.save_anchor(anchor)

    self._disk_offset += PAGE_SIZE
    return stats
```

> ⚠️ **Хвост #3**: Состояние `_disk_offset` и `_disk_window` — только RAM. При рестарте демона сбрасываются в начало. Это intentional — диск сканируется заново. Не сохранять в SQLite.

> ⚠️ **Хвост #4**: `was_productive` в текущей сигнатуре некорректен — статистика `disk_outcomes_updated` всегда 0 при проверке (счётчик ещё не заполнен). Нужен внешний счётчик продуктивности между итерациями (per-pass). Решение: добавить `self._disk_pass_resolved: int = 0` и сбрасывать только при `_disk_offset == 0`.

### 5.3 Интеграция в `dream()`

```python
async def dream(self) -> dict:
    # ... существующий Phase 1 код (RAM scan) ...

    # Phase 2 — disk scan
    disk_stats = await self._disk_scan()
    stats.update(disk_stats)

    # log + return
    ...
```

---

## 6. Индекс: миграция схемы

### 6.1 Новый индекс (schemas.py)

Добавить в `INDICES`:
```python
"CREATE INDEX IF NOT EXISTS idx_anchors_flags_outcome ON anchors(json_extract(flags, '$.outcome'));",
```

> ⚠️ **Хвост #5**: `CREATE INDEX ... ON ... (json_extract(...))` — expression index, поддерживается SQLite 3.9.0+. Проверить в `init_db()` или `check_anchor_schema()`: если `sqlite3.sqlite_version_info < (3, 9, 0)` — логировать warning и пропускать. Функциональность не сломается, просто медленнее.

### 6.2 Миграция (sqlite.py: check_anchor_schema)

Добавить в `check_anchor_schema()`:
```python
try:
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_anchors_flags_outcome "
        "ON anchors(json_extract(flags, '$.outcome'))"
    )
    await db.commit()
except Exception:
    pass  # Expression indices not supported — non-fatal
```

---

## 7. Тесты

**Файл:** `tests/test_dreamer_phase2.py`

| # | Тест | Что проверяет |
|---|------|---------------|
| 1 | `test_find_anchors_by_flags_outcome_pending` | SQL запрос возвращает только pending |
| 2 | `test_find_anchors_by_flags_multi_session` | bool фильтр (json true/false) работает |
| 3 | `test_find_anchors_by_flags_pagination` | offset пагинация возвращает непересекающиеся строки |
| 4 | `test_find_anchors_by_flags_empty` | пустой результат при несовпадении фильтра |
| 5 | `test_find_sessions_by_flags_importance` | фильтр по importance |
| 6 | `test_find_sessions_by_flags_has_tag` | json_each или LIKE fallback |
| 7 | `test_disk_scan_resolves_pending` | `_disk_scan()` находит и разрешает pending anchor с диска |
| 8 | `test_disk_scan_skips_ram_anchors` | anchor уже в ram_index — пропускается |
| 9 | `test_disk_scan_offset_advance` | offset растёт на PAGE_SIZE после каждого вызова |
| 10 | `test_disk_scan_window_expansion` | при 0 resolutions в полном проходе — window * 3 (до 6000) |
| 11 | `test_disk_scan_no_persistence` | `ctx.persistence = None` → 0 checked, нет краша |

> ⚠️ **Хвост #6**: Тесты должны использовать in-memory aiosqlite:
> ```python
> db = await aiosqlite.connect(":memory:")
> ```
> НЕ использовать `Mock()` для DatabaseManager — тестируем реальный SQL.

---

## 8. Чеклист (порядок выполнения)

```
[ ] 1. schemas.py — добавить idx_anchors_flags_outcome в INDICES
[ ] 2. sqlite.py — check_anchor_schema(): миграция индекса  
[ ] 3. sqlite.py — DatabaseManager.find_anchors_by_flags() + json_extract bool fix
[ ] 4. sqlite.py — DatabaseManager.find_sessions_by_flags() + json_each version guard
[ ] 5. persistence.py — proxy-методы find_anchors_by_flags / find_sessions_by_flags
[ ] 6. dreamer.py — _disk_offset, _disk_window, _disk_pass_resolved state
[ ] 7. dreamer.py — _disk_scan() с iterative deepening
[ ] 8. dreamer.py — dream() интеграция _disk_scan()
[ ] 9. tests/test_dreamer_phase2.py — 11 тестов (реальный aiosqlite in-memory)
[ ] 10. npx tsc --noEmit (N/A) + pytest tests/test_dreamer_phase2.py -v
[ ] 11. Repo A: git commit -m "feat(dreamer): Phase 2 disk scan via find_by_flags + iterative deepening"
[ ] 12. Sync public files to Repo C (persistence.py, sqlite.py, dreamer.py, schemas.py, тесты)
```

---

## 9. Неявные проблемы и хвосты (сводка)

| # | Проблема | Файл | Решение |
|---|----------|------|---------|
| T1 | `json_extract` + bool: Python `True` → JSON `true` → SQLite integer `1` | sqlite.py | Преобразовывать `bool → int` перед передачей в параметры |
| T2 | `json_each()` доступен только SQLite 3.38+ | sqlite.py | Runtime version check + LIKE fallback |
| T3 | `_disk_offset`/`_disk_window` сбрасываются при рестарте | dreamer.py | Intentional. Явно задокументировать в docstring |
| T4 | `was_productive` вычисляется до накопления статистики | dreamer.py | Добавить `self._disk_pass_resolved` счётчик |
| T5 | Expression index требует SQLite 3.9+ | schemas.py/sqlite.py | try/except в check_anchor_schema |
| T6 | Тесты через Mock скрывают SQL баги | test_dreamer_phase2.py | Использовать реальный aiosqlite(":memory:") |
| T7 | `decay_level_max=2` исключает bedrock (3) | dreamer.py | Проверить: у bedrock-анкоров outcome всегда stable? Если нет — поднять до 3 |
| T8 | `_disk_scan` запускается каждый dream cycle | dreamer.py | Добавить `dreamer.disk_scan_enabled` в конфиг (config.py + config_default.json) чтобы можно было выключить без перезапуска |
| T9 | Concurrent write во время scan | sqlite.py | WAL mode уже активен — read isolation гарантирована. Дополнительных локов не нужно |
| T10 | `check_anchor_schema` вызывается только при `init_db` (startup) | sqlite.py | Новый индекс появится только при следующем старте — OK, миграция lazy |

---

## 10. Конфигурационные изменения

Добавить в `config.py` (dataclass `DreamerConfig` если есть, иначе в общий):
```python
disk_scan_enabled: bool = True
disk_scan_page_size: int = 50
disk_scan_window_initial: int = 1000
disk_scan_window_max: int = 6000
```

Добавить в `config_default.json` секцию `dreamer`:
```json
"dreamer": {
  "max_anchors_per_cycle": 20,
  "disk_scan_enabled": true,
  "disk_scan_page_size": 50,
  "disk_scan_window_initial": 1000,
  "disk_scan_window_max": 6000
}
```

> ⚠️ **Хвост #8** (продолжение): проверить, существует ли `DreamerConfig` в `config.py`. Если нет — добавить dataclass. Если используется `getattr(cfg, 'dreamer', None)` паттерн из dreamer.py строка 88 — адаптировать к новым полям.

---

## 11. Не затрагиваем

- `_reassess_outcome()` — логика не меняется, вызывается как есть
- RAM Phase 1 (anchor_index.all()) — остаётся без изменений
- `load_anchors(limit=1000)` при bootstrap — не меняется
- Dissolver и Consolidation — не знают о Phase 2
