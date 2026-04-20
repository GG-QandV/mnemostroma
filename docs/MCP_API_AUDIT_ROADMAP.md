# MCP API Audit — Золотой стандарт

## Phase 6.1 | Status: COMPLETED | 2026-04-03

---

## 0. Итог

MCP API приведён в соответствие с архитектурой памяти.
Реализовано 16 агентских инструментов. 7 функций выведены из MCP в демон/CLI/SDK.

**Ключевое архитектурное решение:** агент не управляет физиологией памяти.
Eviction, flush, monitoring — подсознательные процессы демона. Агент только вспоминает.

---

## 1. Инвентаризация — текущее состояние

### 1.1 Сессионный контекст

| #   | MCP name        | Статус | Где реализован                 |
| --- | --------------- | ------ | ------------------------------ |
| 1   | `ctx_active`    | ✅ MCP  | `tools/read.py::ctx_active`    |
| 2   | `ctx_get`       | ✅ MCP  | `tools/read.py::ctx_get`       |
| 3   | `ctx_search`    | ✅ MCP  | `tools/read.py::ctx_search`    |
| 4   | `ctx_semantic`  | ✅ MCP  | `tools/read.py::ctx_semantic`  |
| 5   | `ctx_anchors`   | ✅ MCP  | `tools/read.py::ctx_anchors`   |
| 6   | `ctx_precision` | ✅ MCP  | `tools/read.py::ctx_precision` |
| 7   | `ctx_full`      | ✅ MCP  | `tools/read.py::ctx_full`      |
| 8   | `ctx_bridge`    | ✅ MCP  | `tools/admin.py::ctx_bridge`   |

### 1.2 Контентная ветка

| #   | MCP name          | Статус      | Где реализован                            |
| --- | ----------------- | ----------- | ----------------------------------------- |
| 9   | `content_search`  | ✅ MCP       | `tools/content.py::content_search`        |
| 10  | `content_get`     | ✅ MCP       | `tools/content.py::content_get`           |
| 11  | `content_raw`     | ✅ MCP       | `tools/content.py::content_raw`           |
| 12  | `content_history` | ✅ MCP       | `tools/content.py::content_history`       |
| 13  | `content_diff`    | 🚫 DEFERRED | Требует двойного lz4 + difflib — отложить |
| 14  | `save_content`    | ✅ MCP       | `tools/write.py::save_content`            |

### 1.3 Агентские сервисные инструменты

| #   | MCP name     | Статус | Где реализован               |
| --- | ------------ | ------ | ---------------------------- |
| 15  | `ctx_load`   | ✅ MCP  | `tools/admin.py::ctx_load`   |
| 16  | `ctx_expire` | ✅ MCP  | `tools/write.py::ctx_expire` |
| 17  | `ctx_urgent` | ✅ MCP  | `tools/write.py::ctx_urgent` |

### 1.4 Демон-only (убраны из MCP)

| Функция      | Где живёт                                       | Обоснование                                                                    |
| ------------ | ----------------------------------------------- | ------------------------------------------------------------------------------ |
| `ctx_inject` | `integration/sdk.py::build_memory_context()`    | Функция оркестратора — вызывается до запуска агента, результат в system prompt |
| `ctx_status` | Демон → `~/.mnemostroma/status.json` каждые 30с | Мониторинг — агент не читает RSS процесса                                      |
| `ctx_growth` | CLI: `mnemostroma growth [--db]`                | Аналитика — standalone query к SQLite                                          |
| `ctx_pulse`  | Демон → `~/.mnemostroma/pulse.json` каждые 5с   | Heartbeat — агент не пингует сам себя                                          |
| `ctx_sync`   | `DBManager.flush()` + SIGUSR1                   | Flush — демон-операция, аналог ctx_decay                                       |
| `ctx_dump`   | CLI: `mnemostroma dump` + SIGUSR2               | Debug дамп — CLI/сигнал, не агент                                              |
| `ctx_evict`  | `memory/dissolver.py::Dissolver`                | Eviction — только подсознательный процесс                                      |
| `ctx_decay`  | 🚫 DEFERRED навсегда                            | Decay — только подсознательный процесс (Dissolver)                             |

---

## 2. Итоговый состав MCP

```
Итого в MCP: 16 инструментов
  🧠 Воспоминание: 8  — ctx_full, ctx_anchors, ctx_precision, ctx_bridge,
                         content_search, content_get, content_raw, content_history
  🔍 Навигация:    4  — ctx_semantic, ctx_get, ctx_search, ctx_load
  ⚙️  Сервисный:   4  — ctx_active, ctx_expire, ctx_urgent, save_content
  🚫 Демон-only:   7  — выведены (см. §1.4)
```

---

## 3. Архитектурные решения (зафиксированы 2026-04-03)

| #   | Вопрос                                       | Решение                | Обоснование                                                                                                                       |
| --- | -------------------------------------------- | ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| Q1  | `ctx_bridge` vs `ctx_inject` — один или два? | **Два отдельных**      | `ctx_inject` → SDK оркестратора (не MCP). `ctx_bridge` → MCP: structured handoff следующему агенту. Разные задачи, разные уровни. |
| Q2  | `content_search` — MatrixSearch или FTS5?    | **MatrixSearch**       | Семантический поиск = воспоминание. FTS5 — механический keyword-дамп, противоречит философии памяти.                              |
| Q3  | `ctx_decay` — реализовать или DEFERRED?      | **DEFERRED навсегда**  | Decay — подсознательный процесс Dissolver'а. Агент не вмешивается.                                                                |
| Q4  | Content tools — `write.py` или `content.py`? | **`tools/content.py`** | Чистая ответственность: все content.* операции в одном файле.                                                                     |
| Q5  | Инфраструктурные tools в MCP?                | **Нет**                | ctx_inject/status/growth/pulse/sync/dump — не агентские. Демон/CLI/SDK.                                                           |

---

## 4. Качество реализации

### 4.1 Описания в `list_tools()`

- [x] "HNSW" → "search index" в `ctx_status` (убран из MCP)
- [x] "HNSW" убран из `main()` комментария
- [x] Все Tool.description на русском

### 4.2 Схемы аргументов

- [x] `ctx_semantic`: `top_k` + `top_n` (rerank) — оба параметра
- [x] `save_content`: `content_type`, `session_id`, `tags`, `why_changed`
- [x] `ctx_dump`: `target_dir` optional

### 4.3 Обработка ошибок

- [x] `conductor is None` → `{"error": "Mnemostroma not initialized"}`
- [x] `session not found` → `{"error": "session not found"}`
- [x] `content not found` → `{"error": "content not found"}`
- [x] Стектрейс не пробрасывается — только `str(e)` через общий `except`
- [ ] Специфичный `{"error": ..., "code": ...}` для missing required arg — P3

---

## 5. Тесты

| Файл                          | Тестов   | Покрытие                                                            |
| ----------------------------- | -------- | ------------------------------------------------------------------- |
| `tests/test_tools_read.py`    | 17       | ctx_search, ctx_full, ctx_anchors, ctx_precision                    |
| `tests/test_tools_content.py` | 15       | content_search, content_get, content_raw, content_history           |
| `tests/test_tools_admin.py`   | 11       | ctx_evict (delegation), ctx_load, ctx_growth, ctx_pulse, ctx_bridge |
| `tests/test_dissolver.py`     | 9        | eviction correctness, matrix rebuild, flush guarantee, §5.3         |
| `tests/test_daemon_infra.py`  | 8        | DBManager.flush, PulseWriter, StatusWriter, sdk                     |
| **Итого**                     | **260+** | —                                                                   |

### 5.1 Acceptance-тест (§6 верификация)

```python
EXPECTED_TOOLS = {
    "ctx_active", "ctx_get", "ctx_search", "ctx_semantic",
    "ctx_anchors", "ctx_precision", "ctx_full", "ctx_bridge",
    "ctx_load", "ctx_expire", "ctx_urgent",
    "save_content",
    "content_search", "content_get", "content_raw", "content_history",
}  # 16 инструментов

DAEMON_ONLY = {
    "ctx_inject", "ctx_status", "ctx_growth", "ctx_pulse",
    "ctx_sync", "ctx_dump", "ctx_evict",
}  # никогда не должны появляться в MCP
```

- [x] `test_mcp_list_tools_agent_only` — проверяет что daemon_only отсутствуют
- [ ] `test_mcp_coverage` — полная сверка с EXPECTED_TOOLS (P3)
- [ ] `test_mcp_routing` — каждый tool в list_tools() имеет ветку в call_tool() (P3)

---

## 6. Финальная верификация

- [x] `pytest tests/` → 261 passed
- [x] `grep -r "HNSW\|hnswlib" src/mnemostroma/integration/` → 0 результатов
- [x] `grep -r "HNSW" src/mnemostroma/tools/` → 0 результатов
- [x] `list_tools()` возвращает ровно 16 инструментов
- [x] Каждый tool в `list_tools()` имеет ветку в `call_tool()`
- [x] Dissolver eviction: mapping cleanup + matrix rebuild + flush guarantee
- [x] §5.3 CHECKLIST_v2.md закрыт: `importance × (1 + intensity) × recency_factor`

**Оставшийся P3-долг:**

- `tests/test_mcp_coverage.py` — автоматическая сверка с EXPECTED_TOOLS
- `tests/test_mcp_routing.py` — routing coverage
- `{"error": ..., "code": ...}` для missing required arg

---

*MCP API Audit Roadmap | Phase 6.1 | Updated 2026-04-03*
