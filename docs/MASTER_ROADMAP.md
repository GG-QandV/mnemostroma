# MASTER ROADMAP — Mnemostroma полный план работ
> Обновлён: 2026-04-16 | Предыдущая версия: 2026-04-07 | Версия кода: v1.8.0 | 313+ тестов зелёных

---

## ✅ P1 — create_task долги (DONE 2026-04-04)

Все места, где WorkingMemory вызывала PersistenceLayer через fire-and-forget, переведены на `await`.

| Файл | Строка | Проблема | Фикс | Статус |
|------|--------|----------|------|--------|
| `pipeline.py` | ~269 | `create_task(save_anchor(prev_anchor))` | → `await` | ✅ |
| `consolidation.py` | ~106 | `create_task(upsert_experience(...))` | → `await` | ✅ |
| `consolidation.py` | ~169 | `create_task(save_anchor(anchor))` | → `await` | ✅ |
| `dreamer.py` | ~113 | `create_task(save_anchor(anchor))` | → `await` | ✅ |

Добавлен `test_no_pending_create_tasks_after_pipeline()` в `test_persistence_invariant.py`.

---

## ✅ P2 — Installation UX: скачивание → инсталляция → запуск (DONE 2026-04-07)

### Пользовательская цепочка (CLI User Mode)

```bash
pip install mnemostroma
mnemostroma setup        # инициализация ~/.mnemostroma/ и config.json
mnemostroma on           # запуск демона
mnemostroma status       # проверка состояния
mnemostroma off          # остановка демона
```

### Реализованные CLI команды

**`mnemostroma setup`**
- Создание `~/.mnemostroma/`
- Копирование `config_default.json` → `~/.mnemostroma/config.json`
- Инициализация SQLite БД

**`mnemostroma on`**
- Запуск фонового процесса (демонизация)
- Запись PID в `~/.mnemostroma/daemon.pid`

**`mnemostroma off`**
- Чтение PID и корректная остановка процесса (SIGTERM)

**`mnemostroma status`**
- Чтение `status.json` (uptime, RAM, anchors, metrics)

---

## 🟠 P2 — LLM Chat Integration

### HTTP API — отложено → Pro/Enterprise, не входит в Core
Реализована только базовая инфраструктура `PulseWriter`/`StatusWriter`. Полноценный HTTP-сервер перенесён в коммерческую версию.

| Метод | Путь | Назначение | Статус |
|-------|------|-----------|--------|
| POST | `/observe` | принять текст из браузера | Отложено |
| GET | `/status` | состояние демона | Частично (через файл) |

---

## 🟡 P3 — Красивый старт демона (v1.7.x)

Реализован базовый CLI-интерфейс в `mnemostroma setup` и `on`. ASCII-логотип и статус инициализации.

---

## 🟡 P3 — Windows / macOS service

**`mnemostroma install-service`** / **`mnemostroma uninstall-service`**

- **Linux** → в процессе (systemd)
- **macOS** → запланировано (launchctl)
- **Windows** → запланировано

---

## ✅ Фаза 9.2 — PersistenceLayer/WorkingMemory Split (DONE 2026-04-07)

Реализован формальный интерфейс `PersistenceLayer` для отделения логики WorkingMemory от деталей реализации SQLite.
1. Введён интерфейс `PersistenceLayer.schedule(write_op)` / `PersistenceLayer.sync()`
2. Все вызовы записи в `pipeline.py`, `consolidation.py`, `dreamer.py` переведены на `await ctx.persistence.*`
3. `Conductor.start()` разбит на этапы инициализации PersistenceLayer и последующей гидратации WorkingMemory
4. Обновлены тесты (test_bridge.py) для работы с моком PersistenceLayer

---

## ✅ Фаза 7 — Doc Updates (DONE 2026-04-16)

Обновлены: `CHECKLIST_v2.md`, `MASTER_ROADMAP.md`. Остальные (INDEX_v5, architecture_overview, stack_specification) — актуализация по мере релизов.

---

## ✅ Фаза 11 — v1.8.0 Hexagonal + Proxy + Capture (DONE 2026-04-16)

- Hexagonal refactor (Ports & Adapters, StepChain)
- HTTP Proxy TLS + Gemini OAI routes + `/capture` endpoint
- BackupWorker (периодический SQLite dump)
- RAM оптимизация: lazy NER + MemoryMax=750M systemd
- DB overwrite protection в setup
- B.3 mention_type cosine classification
- Daemon singleton (PID-lock)
- VSCode Extension v0.1.2 — brain/ watcher + Open VSX

---

## ⏳ Фаза 8 — Benchmarks (~2 мес)

precision@5 vs MemGPT / Zep / Mem0 | latency p50/p95/p99 | RAM footprint

---

## Приоритетная последовательность (Status Report)

| # | Задача | Статус |
|---|--------|--------|
| 1 | P1: 4× create_task → await | ✅ Done |
| 2 | `mnemostroma setup/on/off/status` | ✅ Done |
| 3 | HTTP API (Core limited) | 🔵 Deferred |
| 4 | Browser extension MV3 | 🔵 Deferred |
| 5 | Красивый старт | ✅ Done |
| 6 | Windows/macOS service | ⏳ Planned |
| 7 | Фаза 9.2 PersistenceLayer split | ✅ Done |
| 8 | Фаза 7 Doc updates | ✅ Done (2026-04-16) |
| 9 | Фаза 8 Benchmarks | 🔵 Deferred |
| 10 | Фаза 11 v1.8.0 Hexagonal + Proxy | ✅ Done (2026-04-16) |
| 11 | Gemini capture via Continue | ⏳ Проверить 2026-04-23 |
| 12 | `__init__.py` version 1.7.5 → 1.8.0 | ⚠️ Pending |

---

## RAM ⊆ DISK инвариант — статус

| Пункт | Статус |
|-------|--------|
| QueueFull: ERROR лог + `metrics["dropped_sessions"]` | ✅ |
| `upsert_experience`: fire-and-forget → await | ✅ |
| `flush()` drains queue | ✅ |
| `pipeline.py:269` `create_task(save_anchor)` → `await` | ✅ |
| `consolidation.py:106,169` `create_task` → `await` | ✅ |
| `dreamer.py:113` `create_task` → `await` | ✅ |
| Фаза 9.2 — формальный split интерфейсов | ✅ |
| MemoryMax=750M systemd unit | ✅ |

*MASTER_ROADMAP.md | обновлён 2026-04-16 | v1.8.0*
