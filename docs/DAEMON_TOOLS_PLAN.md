# Daemon Tools Plan

## Реализация инфраструктурных функций вне MCP

### Status: TODO | 2026-04-03

---

## Контекст

6 функций убраны из MCP как неагентские. Они нужны для мониторинга, отладки и оркестрации,
но агент не должен знать об инфраструктуре памяти — так же как человек не управляет
своей нейрохимией. Каждая получает правильный дом: демон / CLI / SDK.

---

## 1. ctx_pulse → Демон: pulse writer

**Что делает:** Записывает минимальный снапшот состояния в файл каждые N секунд.

**Файл:** `~/.mnemostroma/pulse.json`

```json
{"sessions": 42, "ram_mb": 187.3, "ram_pct": 29.7, "urgency_active": 2, "ts": 1743680000}
```

**Реализация:**

- [ ] `memory/daemon_metrics.py` — новый файл
- [ ] `class PulseWriter` с методом `async def start(ctx, interval=5.0)`
- [ ] Пишет pulse.json через `aiofiles` или sync (файл маленький)
- [ ] Conductor.start() запускает PulseWriter как background task
- [ ] `mnemostroma watch` и `mnemostroma tray` читают pulse.json — уже делают это

**Зависимости:** Conductor, SystemContext
**Приоритет:** P1 — watch/tray уже ждут этот файл

---

## 2. ctx_status → Демон: status writer

**Что делает:** Расширенный снапшот — RAM, matrix count, queue depth. Обновляется реже.

**Файл:** `~/.mnemostroma/status.json`

```json
{
  "ts": 1743680000,
  "ram_mb": 187.3,
  "ram_index_count": 42,
  "session_index_count": 38,
  "content_index_count": 15,
  "pending_writes": 3,
  "metrics": {...}
}
```

**Реализация:**

- [ ] `memory/daemon_metrics.py` — метод `async def start_status_writer(ctx, interval=30.0)`
- [ ] Использует существующую логику `ctx_status()` из tools/admin.py
- [ ] Conductor.start() запускает status_writer как background task
- [ ] `mnemostroma logs` читает status.json для вывода системной статистики

**Зависимости:** PulseWriter (общий файл-паттерн)
**Приоритет:** P2

---

## 3. ctx_sync → Демон: auto-flush + SIGUSR1

**Что делает:** Периодический flush write queue + по сигналу.

**Реализация A — периодический flush:**

- [ ] DBManager уже имеет `_write_loop` — проверить есть ли там flush по таймеру
- [ ] Если нет — добавить `flush_interval_sec` в config.resources (default: 30)
- [ ] DBManager._write_loop вызывает flush каждые N секунд если очередь непустая

**Реализация Б — flush по сигналу:**

- [ ] `conductor.py` — в `start()` регистрировать SIGUSR1 handler:
  
  ```python
  import signal
  loop.add_signal_handler(signal.SIGUSR1,
      lambda: asyncio.ensure_future(ctx.db_manager.flush()))
  ```
- [ ] CLI: `kill -USR1 $(cat ~/.mnemostroma/daemon.pid)` или `mnemostroma sync`

**Зависимости:** DBManager, Conductor
**Приоритет:** P1 — flush гарантия уже нужна Dissolver'у

---

## 4. ctx_dump → CLI команда + SIGUSR2

**Что делает:** Дамп Hot/Warm слоя в JSON для отладки.

**Реализация A — CLI:**

- [ ] `__main__.py` — добавить команду `dump`:
  
  ```
  mnemostroma dump [--dir PATH]
  ```
- [ ] Вызывает `ctx_dump(ctx)` из tools/admin.py
- [ ] Выводит путь к файлу в stdout

**Реализация Б — по сигналу (для работающего демона):**

- [ ] Conductor.start() регистрирует SIGUSR2 handler → вызывает ctx_dump
- [ ] Пишет в `~/.mnemostroma/dumps/dump_{ts}.json`

**Зависимости:** Conductor, tools/admin.py::ctx_dump (уже есть)
**Приоритет:** P3 — нужно для отладки, не критично

---

## 5. ctx_growth → CLI команда

**Что делает:** Отчёт о росте данных: сессии/день/неделя/месяц, прогноз до 1GB/10GB.

**Реализация:**

- [ ] `__main__.py` — добавить флаг `mnemostroma logs --growth`
- [ ] Или отдельная команда `mnemostroma growth`
- [ ] Выводит таблицу в терминал (rich / plain text)
- [ ] Опционально: cron-задача `mnemostroma growth --report >> growth.log`

**Зависимости:** tools/admin.py::ctx_growth (уже есть), aiosqlite
**Приоритет:** P3 — аналитика

---

## 6. ctx_inject → SDK-функция оркестратора

**Что делает:** Генерирует `<memory_context>` XML для инъекции в системный промпт агента.

**Почему не MCP и не демон:** Это функция уровня оркестратора — вызывается **перед** запуском
агента, результат вставляется в system prompt. Агент получает контекст как часть промпта,
не как ответ на инструмент.

**Реализация:**

- [ ] `integration/sdk.py` — новый файл (публичный SDK для оркестраторов)
- [ ] `async def build_memory_context(user_message, ctx, max_tokens=600) -> str`
- [ ] Использует логику из `proxy.py::inject()` (или заменяет её)
- [ ] Пример использования:
  
  ```python
  from mnemostroma.integration.sdk import build_memory_context
  memory_xml = await build_memory_context(user_message, conductor.ctx)
  system_prompt = BASE_SYSTEM + "\n" + memory_xml
  response = await llm.call(system=system_prompt, ...)
  ```
- [ ] proxy.py::inject() становится тонкой обёрткой над build_memory_context

**Зависимости:** proxy.py (рефакторинг), Conductor
**Приоритет:** P2 — нужно для правильной архитектуры оркестратора

---

## 7. Общая инфраструктура

### PID-файл

- [ ] Conductor.start() пишет PID в `~/.mnemostroma/daemon.pid`
- [ ] Conductor.stop() удаляет PID-файл
- [ ] Нужен для `kill -USR1` / `kill -USR2` из CLI

### daemon_metrics.py — общий модуль

- [ ] PulseWriter (п.1) и StatusWriter (п.2) — в одном файле
- [ ] Оба запускаются через Conductor как asyncio tasks
- [ ] `async def start_daemon_metrics(ctx)` — точка входа

---

## Порядок реализации

```
П.3 (auto-flush) → независимо, нужен уже сейчас
П.1 (pulse)      → watch/tray уже читают pulse.json
П.6 (SDK)        → разблокирует правильное использование ctx_inject
П.2 (status)     → после pulse, тот же паттерн
П.4 (dump)       → CLI + SIGUSR2
П.5 (growth)     → CLI, низкий приоритет
```

---

## Статус реализации ✅

| Функция      | Реализация                                                       | Статус |
| ------------ | ---------------------------------------------------------------- | ------ |
| `ctx_pulse`  | `memory/daemon_metrics.py::PulseWriter` → Conductor              | ✅      |
| `ctx_status` | `memory/daemon_metrics.py::StatusWriter` → Conductor             | ✅      |
| `ctx_sync`   | `storage/sqlite.py::DBManager.flush()` + SIGUSR1 в `__main__.py` | ✅      |
| `ctx_dump`   | CLI `mnemostroma dump` + SIGUSR2 в `__main__.py`                 | ✅      |
| `ctx_growth` | CLI `mnemostroma growth [--db]` → standalone async query         | ✅      |
| `ctx_inject` | `integration/sdk.py::build_memory_context()`                     | ✅      |

**Дополнительно:**

- `~/.mnemostroma/daemon.pid` — пишется при старте, удаляется при стопе
- `~/.mnemostroma/pulse.json` — обновляется каждые 5с
- `~/.mnemostroma/status.json` — обновляется каждые 30с
- `~/.mnemostroma/dumps/dump_{ts}.json` — по SIGUSR2

**Тесты:** `tests/test_daemon_infra.py` — 8 тестов (flush, pulse, status, sdk)

---

*Daemon Tools Plan | 2026-04-03*
