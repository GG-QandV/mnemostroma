# Mnemostroma — Implementation Checklist v2

> Обновлён: 2026-04-16 | Предыдущая версия: 2026-04-08
> 313+ тестов зелёные. Версия: v1.8.0

---

## ✅ ФАЗА 1 — HNSW → Numpy Matrix Search

Выполнено. `hnswlib` убран из `pyproject.toml`. `hnsw.py` перепрофилирован
в `MatrixSearch` (numpy cosine, ADR-002). `hnsw_session/hnsw_lock` убраны из `src/`.

- [x] `test_behavioral.py` — `HNSWIndex` → `MatrixSearch` (2 места, 2026-04-04)

---

## ✅ ФАЗА 2 — marker() вместо filter()

Выполнено. `observer/entities.py`, `observer/marker.py` реализованы и интегрированы
в `pipeline.py`. `TemporalMarker`, `TemporalRelations`, `Entity`, `Emotion`,
`Atmosphere`, `MarkerResult` — все dataclasses живые.

---

## ✅ ФАЗА 3 — Anchor Decay Engine

Выполнено. `memory/consolidation.py` содержит decay worker.
`Anchor.apply_decay()` реализован. Конфиг `anchor_decay` в `config.py`.

---

## ✅ ФАЗА 4 — Dreamer (Stage D)

Выполнено. `subconscious/dreamer.py` реализован. Idle detection в `conductor.py`.
Фоновый пересмотр `flags["outcome"]`, resurface по `access_count`.

---

## ✅ ФАЗА 5 — Memory Model v2: недостающие слои

### ✅ 5.1 Temporal Relations Graph (t_rel)

Выполнено (2026-04-04). `Anchor.t_rel` поле, `check_anchor_schema()` миграция,
`save_anchor/load_anchors/get_anchor` обновлены (12 колонок).
`pipeline.py` читает `t_rel` из `mark_result.entity.t_rel`.
`ctx_anchors` возвращает `t_rel`. 12 тестов в `test_temporal_relations.py`.

### ✅ 5.2 Pending Emotion Resolution

Выполнено. `pending_emotions: List[Emotion]` в `SystemContext`.
`resolve_pending_emotions()` вызывается в `pipeline.py`.

### ✅ 5.3 RAM Eviction Formula v2

Выполнено. `priority = importance × (1 + intensity) × recency_factor`
в `memory/dissolver.py`. Тест `test_high_intensity_not_evicted_first`.

### ✅ 5.4 Emotional Patterns Layer

Выполнено. `ExperienceCluster` расширен: `emotion_positive`, `emotion_negative`,
`emotion_intensity_sum`, `record_emotion()`, `emotion_signal` (ATTRACT/REPEL/AMBIVALENT).
`ExperienceIndex.update_emotion()`. Сигналы в `intuition_signals()`.
SQLite: 3 новых колонки + `check_experience_schema()` миграция.
`pipeline.py` step 7c + step 1.5 NER micro-pipe.

---

## ✅ ФАЗА 6 — Quality & Coverage

### ✅ 6.1 MCP API Audit

Выполнено. 16 агентских инструментов (было 22). Daemon-only убраны из MCP.
`KeyError` handler (`code: "missing_arg"`). Тесты: `test_mcp_coverage.py`,
`test_mcp_routing.py` (статический аудит routing через inspect+regex).

### ✅ 6.2 Reranker E2E Test

Выполнено. `tests/test_reranker_integration.py` — 12 тестов.
Embedder: shape (384,), float16, L2-norm, cosine similarity, aencode.
Reranker: scores [0,1], relevant > irrelevant, output format, lazy load.
Попутно исправлен баг в `memory/reranker.py`: `outputs[0][0]` shape `(1,)` → `float(np.squeeze(outputs[0]))`.

---

## ✅ Daemon Infrastructure (вне фаз роадмапа)

Выполнено. `DBManager.flush()`, `PulseWriter`, `StatusWriter`,
`SDK.build_memory_context()`, SIGUSR1/SIGUSR2 handlers,
CLI команды `dump` и `growth`. Conductor wired. 8 тестов в `test_daemon_infra.py`.

---

## ✅ ФАЗА 7 — Doc Updates & CLI Mode

Выполнено (2026-04-07).
- [x] Все спецификации (`INDEX_v5.md`, `architecture_overview.md`, `data_flow_specification.md`, `stack_specification.md`, `api_tools_specification.md`) синхронизированы с v1.7.1.
- [x] CLI User Mode: реализованы `setup`, `on`, `off`, `status`, `mcp`, `service install/uninstall`.
- [x] Автоматическая установка моделей ONNX через `setup`.
- [x] Генерация `claude_desktop_config.json` блока в `setup`.
- [x] Корректный резолвинг путей моделей относительно `~/.mnemostroma/`.
- [x] `pyproject.toml`: добавлены классификаторы, удалён `gliner`, добавлен `mcp`.

---

## ✅ ФАЗА 9 — PersistenceLayer / WorkingMemory Split (P2)

> Предпосылка: архитектурный инвариант RAM ⊆ DISK, анализ 2026-04-04.
> CM: `cm_search("persistence-invariant-fix")`

Выполнено. Введён `PersistenceLayer` как единственная точка доступа к SQLite для WorkingMemory.

### 9.1 Закрыть P1-долги (✅ сделано 2026-04-04)

- [x] `sqlite.py`: `QueueFull` → ERROR + `metrics["dropped_sessions"]`
- [x] `pipeline.py:351`: `create_task(upsert_experience)` → `await`
- [x] `test_persistence_invariant.py` — 8 тестов

### 9.2 Формализовать границу (✅ сделано 2026-04-07)

- [x] Ввести интерфейс `PersistenceLayer.schedule(write_op)` —
      WorkingMemory не держит прямую ссылку на `db_manager`
- [x] `pipeline.py:269` — `create_task(save_anchor(prev_anchor))` →
      через `persistence_callback`
- [x] `consolidation.py:106` — `create_task(upsert_experience)` →
      через `persistence_callback`
- [x] `consolidation.py:169` — `create_task(save_anchor(anchor))` →
      через `persistence_callback`
- [x] `dreamer.py:113` — `create_task(save_anchor(anchor))` →
      через `persistence_callback`
- [x] `Conductor.start()` разбить на
      `PersistenceLayer.start()` → `WorkingMemory.hydrate(persistence)` →
      workers start
- [x] Тесты: WorkingMemory hydrate из mock PersistenceLayer без реального SQLite (test_bridge.py)

---

## ✅ ФАЗА 10 — Claude.ai Connector & Browser Integration

Выполнено (2026-04-08).

- [x] **IPC Server (`ipc_server.py`)**: Реализован проброс инструментов через Unix-сокеты/Named Pipes для разделения процессов демона и адаптеров.
- [x] **MCP STDIO Adapter**: Тонкий прокси для Claude Code.
- [x] **MCP SSE Adapter (`mcp_sse_adapter.py`)**: Реализован транспорт для подключения claude.ai с поддержкой Bearer TOKEN авторизации.
- [x] **Browser Extension**: Реализован захват DOM истории чата в реальном времени и отправка на локальный эндпоинт `/observe` (порт 8766).
- [x] **Token Auth**: Автоматическая генерация и проверка токенов в `~/.mnemostroma/sse_token`.
- [x] **CLI**: Добавлена команда `mnemostroma sse` для быстрого запуска сервера адаптации.

---

## ⏳ ФАЗА 8 — Benchmarks (отложено)

Запланировано через 1-2 месяца после стабилизации.
precision@5 vs MemGPT / Zep / Mem0, latency p50/p95/p99, RAM footprint.

---

## ✅ ФАЗА 11 — v1.8.0 Hexagonal Architecture + Proxy + Capture (2026-04-08 → 2026-04-16)

- [x] **Hexagonal refactor** — Ports & Adapters, StepChain modular pipeline (efb5558, ff2f353, 7d08c66)
- [x] **HTTP Proxy TLS** — `http_proxy.py` переведён на HTTPS, CA-cert, `ANTHROPIC_BASE_URL=https://` (c41f6b9)
- [x] **Proxy: Gemini OAI routes** — `/v1/chat/completions` → `generativelanguage.googleapis.com/v1beta/openai`, SSE parser (f943543)
- [x] **Proxy: /capture endpoint** — POST `/capture` → `_observe()` background task (f943543)
- [x] **BackupWorker** — периодический SQLite dump в `~/.mnemostroma/backups/`, метрики в `db_snapshots` (473ed4d)
- [x] **RAM оптимизация** — lazy NER unload + `gc.collect/malloc_trim` после observer run (e874fe6)
- [x] **MemoryMax=750M** — добавлен в systemd daemon unit (de2a366)
- [x] **DB overwrite protection** — `mnemostroma setup` не затирает существующую БД (878baec)
- [x] **B.3 mention_type** — embedding cosine classification (03deaa0)
- [x] **strip_logs_v2.py** — скрипт авто-удаления `log_event` перед синком в Repo C (8b83754)
- [x] **Daemon singleton** — robust PID-lock + single-instance guarantee (d2d51c3, 9937656)
- [x] **NER bilingual mapping fix** — proxy session cache, IPC protocol alignment (d9c029c)
- [x] **VSCode Extension v0.1.2** — brain/ watcher (Antigravity), /capture POST, Open VSX publish

---

## Сводка

| Статус | Задач |
|--------|-------|
| ✅ Сделано | Фазы 1–7, 9–11, §5.1–5.4, Daemon infra |
| ⏳ Открыто | Фаза 8 (Benchmarks, через 1–2 мес) |
| 🔵 Отложено | VSCode terminal watcher (onDidWriteTerminalData) — прокси покрывает |
| ⏳ Проверить | Gemini capture via Continue — 2026-04-23 |

*Checklist v2 | обновлён 2026-04-16 | v1.8.0 | тесты зелёные*
