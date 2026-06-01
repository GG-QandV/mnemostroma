# SPEC: SSE Adapter Embedded in Daemon

> **Версия:** 1.1 | **Статус:** DRAFT | **Дата:** 2026-06-01
> **Предыдущая версия:** 1.0 (содержала критические ошибки — см. §6)
> **Зависит от:** `bootstrap.py`, `monitoring.py`, `conductor.py`, `mcp_sse_adapter.py`, `ipc_server.py`

---

## 1. Контекст и мотивация

### 1.1 AS-IS

```
Клиент (Claude/Codex/OpenCode/VS Code)
    │
    ▼ stdio × N процессов (~21 MB каждый)
mcp_stdio_adapter.py  [×3 экз. = ~63 MB]
    │ IPC Unix socket / Named Pipe
    ▼
daemon (conductor)
    │
    ▼ (отдельный процесс)
mcp_sse_adapter.py    [port 8765/8766, ~45 MB]
    │ safe_ipc_call → Unix socket
    ▼
daemon (conductor)

mcp_oauth_adapter.py  [port 8769, OAuth proxy → 8765, отдельный процесс]
```

**Проблемы:**
- `mcp_sse_adapter` — отдельный процесс: +45 MB RAM, лишний IPC round-trip
- При падении SSE-адаптера все SSE-клиенты теряют соединение одновременно
- `mnemostroma-sse.service` — лишний systemd unit
- Цепочка: клиент → SSE адаптер → IPC → conductor = 2 hop вместо 1

### 1.2 TO-BE

```
Клиент (Claude/Codex/VS Code/OpenCode)
    │
    ▼ HTTP SSE / Streamable HTTP
    ┌─────────────────────────────────────────┐
    │  daemon process                         │
    │  ┌───────────────────────────────────┐  │
    │  │  asyncio.TaskGroup (monitoring)   │  │
    │  │  ├── ipc_server                  │  │
    │  │  ├── mcp_sse_server  ← NEW       │  │  port 8765 + 8766
    │  │  └── keepalive_loop             │  │
    │  │                                  │  │
    │  │  Conductor (управляет workers):   │  │
    │  │  ├── observer_loop               │  │
    │  │  ├── consolidation_worker        │  │
    │  │  ├── dreamer                     │  │
    │  │  └── backup_worker               │  │
    │  └───────────────────────────────────┘  │
    └─────────────────────────────────────────┘

mcp_oauth_adapter.py  [port 8769 — остаётся отдельным процессом]
```

**Экономия:** ~45 MB RAM, устранение IPC round-trip, -1 systemd unit.

---

## 2. Архитектурные решения

### 2.1 Место запуска SSE-сервера

SSE-сервер запускается как `asyncio.Task` **внутри `TaskGroup` в `monitoring.py`**, а не в `bootstrap.py`.

**Почему не в bootstrap.py** (ошибка v1.0):
```python
# НЕПРАВИЛЬНО (v1.0) — код после await НЕДОСТИЖИМ:
await run_background_workers(conductor)  # блокирует до shutdown
sse_task = asyncio.create_task(...)      # никогда не выполнится
```

`run_background_workers` содержит `asyncio.TaskGroup` с `while True: sleep(86400)` — он не возвращает управление до завершения всех задач. SSE task должен создаваться **внутри** TaskGroup:

```python
# ПРАВИЛЬНО — в monitoring.py:
async with asyncio.TaskGroup() as tg:
    tg.create_task(ipc.serve(), name="ipc_server")
    tg.create_task(
        sse_run(conductor=conductor, port=port, port_ext=port_ext),
        name="mcp-sse-server"
    )
    while True:
        await asyncio.sleep(86400)
```

### 2.2 Direct call — conductor.dispatch() уже существует

`conductor.dispatch(tool, args)` вызывается из `ipc_server.py`:
```python
result = await self._conductor.dispatch(msg["tool"], msg.get("args", {}))
```

Новый метод `handle_tool()` из спека v1.0 **не нужен** — используем `dispatch` напрямую:

```python
# mcp_sse_adapter.py — новая ветка
if conductor is not None:
    result = await conductor.dispatch(name, arguments)
    result = _serialize(result)   # ipc_server._serialize уже есть
else:
    result = await safe_ipc_call(name, arguments)  # fallback: standalone mode
```

**Формат ответа:** `conductor.dispatch()` возвращает raw Python object; `safe_ipc_call` возвращает `response.get("result")` после JSON round-trip. Оба совместимы при условии применения `_serialize()`.

### 2.3 Uvicorn signal handlers — обязательный флаг

`lifecycle.py` регистрирует `SIGTERM`/`SIGINT` через `loop.add_signal_handler`. Uvicorn по умолчанию тоже устанавливает signal handlers и перезапишет daemon'овские.

**Обязательно для каждого uvicorn.Config:**
```python
config = uvicorn.Config(
    app,
    host=host,
    port=port,
    install_signal_handlers=False,  # ← ОБЯЗАТЕЛЬНО при embedded режиме
    log_level="warning",
)
```

### 2.4 Порты и биндинг

| Порт | Назначение | Биндинг | Изменение |
|------|------------|---------|-----------|
| 8765 | MCP SSE primary | `127.0.0.1` | было `0.0.0.0` → меняется |
| 8766 | MCP SSE extension | `127.0.0.1` | без изменений |
| 8769 | OAuth adapter | `127.0.0.1` | без изменений, отдельный процесс |

> **Важно:** Текущий `mcp_sse_adapter.py` биндит порт 8765 на `0.0.0.0`. Изменение на `127.0.0.1` — breaking change для внешних подключений. Если есть тестеры с прямым IP-доступом — сообщить заранее.

### 2.5 Graceful shutdown

Порядок завершения при SIGTERM:

```
1. lifecycle.py::handle_termination() → main_task.cancel()
2. _run_daemon() (commands.py) получает CancelledError
3. finally: await asyncio.shield(conductor.stop())
              ↑ shield защищает flush от прерывания вторым cancel
4. conductor.stop():
   a. sse_task.cancel() + await (timeout 5s)
   b. pulse_writer.stop(), status_writer.stop(), backup_worker.stop()
   c. persistence.stop()  ← flush SQLite WAL
   d. dreamer, consolidation, dissolver stop
5. _remove_pid()
```

**`asyncio.shield` в `_run_daemon()` finally-блоке:**
```python
# commands.py — _run_daemon() finally
finally:
    _remove_pid()
    if 'conductor' in locals():
        await asyncio.shield(conductor.stop())
```

Без shield: если event loop получает второй SIGTERM пока conductor.stop() делает flush — операция прерывается с потерей данных.

### 2.6 SSE task — lifecycle в conductor.stop()

```python
# conductor.py — в начале stop()
async def stop(self) -> None:
    self._stopping = True

    # Остановить SSE сервер первым — закрыть клиентские соединения
    sse_task = getattr(self, "_sse_task", None)
    if sse_task and not sse_task.done():
        sse_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(sse_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # ... существующий shutdown sequence
```

`_sse_task` устанавливается из `monitoring.py` после создания задачи:
```python
conductor._sse_task = tg.create_task(sse_run(...), name="mcp-sse-server")
```

---

## 3. Изменения в коде

### 3.1 `src/mnemostroma/core/monitoring.py`

Добавить SSE task в TaskGroup. Читать конфиг из conductor:

```python
async def run_background_workers(conductor: "Conductor") -> None:
    async with asyncio.TaskGroup() as tg:
        logger.info("Starting background workers TaskGroup...")

        from mnemostroma.ipc_server import IPCServer
        ipc = IPCServer(conductor)
        tg.create_task(ipc.serve(), name="ipc_server")

        # NEW: встроенный SSE сервер
        cfg = getattr(conductor, "config", {}) or {}
        sse_cfg = cfg.get("sse", {}) if isinstance(cfg, dict) else {}
        if sse_cfg.get("autostart", True):
            from mnemostroma.integration.mcp_sse_adapter import run as sse_run
            sse_task = tg.create_task(
                sse_run(
                    conductor=conductor,
                    port=sse_cfg.get("port", 8765),
                    port_ext=sse_cfg.get("port_extension", 8766),
                    host=sse_cfg.get("host", "127.0.0.1"),
                ),
                name="mcp-sse-server",
            )
            conductor._sse_task = sse_task
            logger.info("Embedded MCP SSE server scheduled on port %s", sse_cfg.get("port", 8765))

        logger.info("Daemon is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(86400)
```

### 3.2 `src/mnemostroma/integration/mcp_sse_adapter.py`

Новая сигнатура `run()`:
```python
async def run(
    conductor=None,
    port: int = 8765,
    port_ext: int | None = 8766,
    host: str = "127.0.0.1",
) -> None:
```

Новая сигнатура `make_mcp_server()`:
```python
def make_mcp_server(conductor=None) -> Server:
    srv = Server("mnemostroma")

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if conductor is not None:
                from mnemostroma.ipc_server import _serialize
                result = await conductor.dispatch(name, arguments)
                return _serialize(result)
            else:
                return await safe_ipc_call(name, arguments)
        except Exception as e:
            logger.error(f"tool {name!r} failed: {e}", exc_info=True)
            raise
```

Uvicorn конфиг — добавить `install_signal_handlers=False`:
```python
mcp_config = uvicorn.Config(
    make_mcp_app(conductor=conductor),
    host=host,
    port=port,
    log_level="warning",
    install_signal_handlers=False,   # ← обязательно в embedded режиме
)
```

### 3.3 `src/mnemostroma/conductor.py`

В начало `stop()` добавить cleanup SSE task (см. §2.6).

### 3.4 `src/mnemostroma/cli/commands.py`

В `_run_daemon()` finally-блок добавить `asyncio.shield`:
```python
finally:
    _remove_pid()
    logger.info("Shutting down daemon...")
    if 'conductor' in locals():
        await asyncio.shield(conductor.stop())
    logger.info("Shutdown complete.")
```

Команда `mnemostroma sse` сохраняется для standalone/debug:
```python
elif command == "sse":
    from mnemostroma.integration.mcp_sse_adapter import run as sse_run
    asyncio.run(sse_run(conductor=None))  # conductor=None → IPC fallback
```

### 3.5 `src/mnemostroma/core/bootstrap.py`

Убрать прямой запуск SSE из bootstrap (он теперь в monitoring.py). Файл не меняется содержательно.

### 3.6 `config_default.json` / `~/.mnemostroma/config.json`

Добавить секцию:
```json
{
  "sse": {
    "autostart": true,
    "port": 8765,
    "port_extension": 8766,
    "host": "127.0.0.1"
  }
}
```

---

## 4. Systemd и сервисы

### 4.1 `mnemostroma-sse.service` — DEPRECATED

Файл остаётся в пакете, но не устанавливается. В `_cmd_service_linux()`:

```python
units = (
    "mnemostroma-daemon.service",
    "mnemostroma-proxy.service",
    "mnemostroma-watchdog.service",
    "mnemostroma-ui.service",
    # "mnemostroma-sse.service",  # REMOVED: SSE embedded in daemon
    "mnemostroma-tunnel.service",
)
```

Добавить заголовок в `mnemostroma-sse.service`:
```ini
# DEPRECATED: SSE adapter is now embedded in mnemostroma-daemon.
# Use ONLY for standalone/debug mode.
# To re-enable standalone: mnemostroma config set sse.autostart false
#                          systemctl --user enable --now mnemostroma-sse
```

### 4.2 Migration для существующих установок

**Риск конфликта портов:** если `mnemostroma-sse.service` уже `enabled`, при обновлении daemon запустит встроенный SSE на 8765, а старый сервис тоже попытается занять 8765 → один упадёт.

В installer/upgrade скрипте обязательно:
```bash
systemctl --user disable --now mnemostroma-sse.service 2>/dev/null || true
```

### 4.3 Watchdog (`watchdog.py`)

SSE теперь внутри daemon — если daemon жив и heartbeat свеж, SSE скорее всего жив.

Однако: asyncio task может упасть пока daemon живёт. Watchdog должен проверять порт 8765 аналогично тому как проверяет 8767:

```python
async def _sse_healthy(timeout: int = 2) -> bool:
    """TCP connect check к embedded SSE (порт 8765)."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 8765),
            timeout=timeout,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False
```

В Phase 2: при `not _sse_healthy()` — логировать WARNING (не убивать daemon целиком, SSE может восстановиться).

> **Примечание:** `/health` endpoint с `sse_alive: true`, упомянутый в v1.0, не реализован и не нужен — TCP connect на 8765 достаточен.

---

## 5. Клиентские конфиги после перехода

После деплоя все stdio-клиенты переключаются на SSE:

**`~/.claude/mcp.json`:**
```json
{
  "mcpServers": {
    "mnemostroma": {
      "type": "sse",
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

**`~/.codex/config.toml`:**
```toml
[mcp_servers.mnemostroma]
url = "http://127.0.0.1:8765/sse"
```

**OpenCode `opencode.json`:**
```json
{
  "mcp": {
    "mnemostroma": {
      "type": "remote",
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

**VS Code `mcp.json`:**
```json
{
  "servers": {
    "mnemostroma": {
      "type": "sse",
      "url": "http://127.0.0.1:8765/sse"
    }
  }
}
```

---

## 6. Diff от v1.0 — исправленные ошибки

| # | Проблема v1.0 | Исправление в v1.1 |
|---|--------------|-------------------|
| **CR-1** | SSE task создавался в bootstrap.py ПОСЛЕ `await run_background_workers()` — недостижимый код | Перенесён внутрь TaskGroup в `monitoring.py` |
| **CR-2** | uvicorn signal handlers конфликтуют с lifecycle.py | `install_signal_handlers=False` обязателен |
| **CR-3** | `conductor.handle_tool()` — несуществующий метод | Используется `conductor.dispatch()` (уже есть в ipc_server.py) |
| **GAP-1** | `/health` endpoint с `sse_alive` — нигде не реализован | Заменён TCP connect check на 8765 в watchdog |
| **GAP-2** | Migration существующих установок с sse.service | Добавлен `disable --now` в upgrade script |
| **GAP-3** | Error handling в direct call path | `try/except` с re-raise в call_tool handler |
| **INC-1** | `asyncio.shield` упомянут в §2.4 но отсутствовал в коде | Добавлен в `_run_daemon()` finally-блок |
| **INC-2** | Shutdown order в §2.4 vs §3.3 противоречили | Унифицировано: sse_task cancel внутри conductor.stop() |
| **MIN-1** | Порт 8765 биндился на `0.0.0.0` — breaking change не обозначен | Явно указан как breaking change в §2.4 |
| **MIN-2** | `conductor._sse_task` присваивался из bootstrap | Присваивается из monitoring.py, ближе к месту создания task |

---

## 7. Тесты

Новые тесты к реализации:

| ID | Что проверяет |
|----|--------------|
| TEST-SSE-EMB-001 | SSE сервер стартует внутри TaskGroup при `autostart: true` |
| TEST-SSE-EMB-002 | SSE сервер не стартует при `autostart: false` |
| TEST-SSE-EMB-003 | `conductor.dispatch()` вызывается напрямую когда `conductor != None` |
| TEST-SSE-EMB-004 | Fallback на `safe_ipc_call` когда `conductor=None` |
| TEST-SSE-EMB-005 | `install_signal_handlers=False` передаётся в uvicorn.Config |
| TEST-SSE-EMB-006 | `conductor.stop()` отменяет SSE task и ждёт завершения (timeout 5s) |
| TEST-SSE-EMB-007 | `asyncio.shield` в `_run_daemon()` защищает flush при двойном cancel |
| TEST-SSE-EMB-008 | Watchdog логирует WARNING при недоступном порту 8765 (не убивает daemon) |
