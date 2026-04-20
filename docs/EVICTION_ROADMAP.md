# Eviction Roadmap — ctx_evict & Dissolver
## Status: GAPS FOUND | 2026-04-03

---

## 0. Текущее состояние (что уже есть)

| Компонент | Статус | Что делает |
|---|---|---|
| `memory/dissolver.py::evict_n_oldest` | ✅ есть | Удаляет из `ram_index`, использует правильную формулу приоритета |
| `memory/dissolver.py::_eviction_priority` | ✅ есть | `importance × (1 + intensity) × recency_factor` — это и есть формула v2 из чеклиста §5.3 |
| `memory/dissolver.py::can_evict` | ✅ есть | Защищает principle, live deadlines, conflict_flag |
| `memory/dissolver.py::check_and_evict` | ✅ есть | Триггер по count > 80% window_size |
| `tools/admin.py::ctx_evict` | ⚠️ дублирует | Другая логика (по score), чистит mappings, но НЕ Dissolver |

**Вывод:** Dissolver — правильная реализация. `tools/admin.py::ctx_evict` — дубль с отклонением от спеки.

---

## 1. Найденные проблемы (баги)

### P0 — критический: матрица не обновляется при eviction

`evict_n_oldest` удаляет из `ram_index` но **не трогает**:
- `ctx.session_index` (MatrixSearch) — вектор мёртвой сессии остаётся
- `ctx.sid_to_id` — маппинг не чистится
- `ctx.id_to_sid` — маппинг не чистится

**Последствие:** `knn_query` после eviction может вернуть label мёртвой сессии →
`ctx.id_to_sid.get(label)` → `None` → candidate пропускается, но матрица засоряется.
При длительной работе матрица растёт без ограничений.

### P1 — важный: нет гарантии персистентности перед eviction

Сессия может быть в write queue (не зафиксирована в SQLite) в момент eviction из RAM.
Если процесс упадёт — данные потеряны.

### P2 — технический долг: дублирование логики

`tools/admin.py::ctx_evict` и `dissolver.py::evict_n_oldest` — две реализации eviction
с разной логикой. Нарушение single-source-of-truth.

### P3 — minor: asyncio import внизу файла (строка 95)

`import asyncio` в конце `dissolver.py` вместо начала файла.

---

## 2. Чеклист исправлений (в порядке зависимостей)

### Шаг 1: P3 — asyncio import ✅
- [x] `memory/dissolver.py` — `import asyncio` перемещён в начало файла

### Шаг 2: P0 — чистка маппингов в Dissolver ✅
- [x] `memory/dissolver.py::evict_n_oldest` — после `del self.ctx.ram_index[sb.session_id]` чистятся `sid_to_id` / `id_to_sid`
- [x] Тест: `test_evict_cleans_sid_to_id`, `test_evict_cleans_id_to_sid`

### Шаг 3: P0 — rebuild MatrixSearch после eviction ✅
- [x] `memory/dissolver.py::evict_n_oldest` — вызывает `_rebuild_session_index(ctx)` после batch eviction
- [x] `_rebuild_session_index(ctx)` реализован в dissolver.py — полный rebuild из ram_index
- [x] `memory/hnsw.py::MatrixSearch.clear()` — сброс `_vectors` + `_labels`
- [x] Тест: `test_rebuild_removes_evicted_vectors`, `test_evict_rebuild_knn_no_dead_labels`

### Шаг 4: P1 — гарантия персистентности перед eviction ✅
- [x] `memory/dissolver.py::evict_n_oldest` — `await self.ctx.db_manager.flush()` перед удалением (вариант А)
- [x] Тест: `test_flush_called_before_eviction`

### Шаг 5: P2 — убрать дублирование ✅
- [x] `tools/admin.py::ctx_evict` — делегирует в `ctx.dissolver.evict_n_oldest(n)`, возвращает diff
- [x] Тест: `test_ctx_evict_delegates_to_dissolver`

### Шаг 6: §5.3 из чеклиста ✅
- [x] `_eviction_priority` реализует: `importance × (1 + intensity) × recency_factor`
- [x] Тест: `test_high_intensity_not_evicted_first`
- [x] CHECKLIST_v2.md §5.3 помечен как ✅

---

## 3. Зависимости между шагами

```
Шаг 1 (import) → независимый
Шаг 2 (маппинги) → должен быть ДО Шага 3 (rebuild)
Шаг 4 (flush) → независимый, можно параллельно с Шагом 3
Шаг 5 (дедупликация) → после Шагов 2+3 (нужна правильная версия)
Шаг 6 (закрыть §5.3) → после всех
```

---

## 4. Тесты (итого)

- [ ] `tests/test_dissolver.py` — новый файл или расширение существующего:
  - После eviction N сессий: `len(ram_index)` уменьшился на N
  - После eviction: evicted session_id отсутствует в `sid_to_id`
  - После eviction: evicted label отсутствует в `id_to_sid`
  - После eviction + rebuild: `knn_query` не возвращает мёртвые labels
  - can_evict: principle → False
  - can_evict: live deadline → False
  - can_evict: conflict_flag → False
  - Flush перед eviction: pending session сохраняется в SQLite
  - §5.3: высокая intensity → не первый в очереди на eviction

---

## 5. Что НЕ трогаем

- `check_and_evict` — логика триггера правильная, не меняем
- `_run_loop` — интервал из config, ок
- `can_evict` правила — правильные, не меняем
- `ctx_evict` НЕ возвращается в MCP — это daemon-only навсегда

---

## 6. Коммит

```
fix(dissolver): eviction correctness — matrix rebuild + mapping cleanup + flush guarantee

- evict_n_oldest: clean sid_to_id + id_to_sid on eviction
- _rebuild_session_index: full MatrixSearch rebuild after batch eviction
- MatrixSearch.clear(): reset matrix + labels
- flush before eviction: guarantee SQLite persistence
- ctx_evict delegates to Dissolver (single source of truth)
- asyncio import moved to file header
- tests: 9 new cases covering matrix integrity + §5.3 formula
```

---

*Eviction Roadmap | 2026-04-03*
