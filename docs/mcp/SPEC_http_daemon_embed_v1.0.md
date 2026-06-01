# SPEC: Streamable HTTP Adapter Embedded in Daemon

> **Версия:** 1.0 | **Статус:** DRAFT | **Дата:** 2026-06-01
> **Зависит от:** `bootstrap.py`, `monitoring.py`, `conductor.py`, `mcp_http_adapter.py`, `ipc_server.py`
> **Смотри также:** `SPEC_sse_daemon_embed_v1.1.md` — аналогичная операция для SSE адаптера

---

## 1. Контекст и мотивация

### 1.1 AS-IS

```
Клиент (Codex / Antigravity / VS Code / Cursor)
    │
    ▼ Streamable HTTP
mcp_http_adapter.py  [port 8768, отдельный процесс, ~45 MB]
    │ safe_ipc_call → Unix socket
    ▼
daemon (conductor)

mcp_stdio_adapter.py [×N процессов, ~20 MB каждый — для клиентов без HTTP]
    │ IPC Unix socket
    ▼
daemon (conductor)
```

**Проблемы:**
- `mcp_http_adapter` — отдельный процесс: +45 MB RAM, лишний IPC round-trip
- `mnemostroma-http.service` — лишний systemd unit
- Цепочка: клиент → HTTP адаптер → IPC → conductor = 2 hop вместо 1
- `safe_ipc_call` добавляет JSON round-trip и latency
- stdio процессы множатся: по одному на каждый клиент

### 1.2 TO-BE

```
Клиент (Codex / Antigravity / VS Code / Cursor / Claude CLI)
    │
    ▼ Streamable HTTP  (порт 8768)
    ┌─────────────────────────────────────────┐
    │  daemon process                         │
    │  ┌───────────────────────────────────┐  │
    │  │  asyncio.TaskGroup (monitoring)   │  │
    │  │  ├── ipc_server                  │  │
    │  │  ├── mcp_sse_server  (8765)      │  │
    │  │  ├── mcp_http_server ← NEW (8768)│  │
    │  │  └── keepalive_loop             │  │
    │  │                                  │  │
    │  │  Conductor (управляет workers)   │  │
    │  └───────────────────────────────────┘  │
    └─────────────────────────────────────────┘

mcp_oauth_adapter.py  [port 8769 — остаётся отдельным процессом]
```

**Выгода:** ~45 MB RAM, устранение IPC round-trip, -1 systemd unit, единый транспорт для всех современных клиентов.

---

## 2. Архитектурные решения

### 2.1 Lifecycle StreamableHTTPSessionManager

`StreamableHTTPSessionManager` требует запуска через async context manager `sm.run()` до того, как начнут поступать запросы. В текущей реализации это сделано через Starlette `lifespan`.

**В embedded режиме `lifespan` сохраняется** — uvicorn вызывает его при старте. Порядок:

```
monitoring.py TaskGroup
    └── tg.create_task(http_run(conductor=conductor, port=8768))
            └── uvicorn.Server(make_mcp_app(conductor)).serve()
                    └── Starlette lifespan:
                            async with sm.run():
                                app.state.sm = sm
                                yield   ← uvicorn обслуживает запросы
                        ← при отмене task: uvicorn shutdown → lifespan exit → sm.stop()
```

Это чистая схема: SM живёт ровно столько, сколько uvicorn.

### 2.2 conductor.dispatch() — прямой вызов

Текущий адаптер использует `safe_ipc_call` (JSON round-trip через Unix socket). В embedded режиме — прямой вызов `conductor.dispatch()`:

```python
# mcp_http_adapter.py — _make_mcp_server() с conductor
@srv.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        if conductor is not None:
            from mnemostroma.ipc_server import _serialize
            raw = await conductor.dispatch(name, arguments)
            result = _serialize(raw)
        else:
            result = await safe_ipc_call(name, arguments)  # standalone fallback
        ...
```

### 2.3 tools_changed=True — убрать

Текущий `_make_mcp_server()` выставляет `NotificationOptions(tools_changed=True)`. Ряд клиентов (Codex) при виде `listChanged: true` в capabilities **ждёт нотификацию** вместо того чтобы запросить `tools/list` сразу → инструменты не появляются при старте.

**Убрать переопределение `create_initialization_options`** — как уже сделано в SSE адаптере.

### 2.4 install_signal_handlers

uvicorn 0.46.0 **не поддерживает** параметр `install_signal_handlers` в `uvicorn.Config`. Не использовать. Конфликта signal handlers нет: uvicorn в embedded режиме получает отмену через `task.cancel()`, а не через SIGTERM напрямую.

### 2.5 Порты и биндинг

| Порт | Назначение | Биндинг | Изменение |
|------|------------|---------|-----------|
| 8768 | MCP Streamable HTTP | `127.0.0.1` | было `0.0.0.0` → меняется |
| 8766 | Observe (extension) | `127.0.0.1` | без изменений |

> **Важно:** текущий `mcp_http_adapter.py` биндит 8768 на `0.0.0.0`. Изменение на `127.0.0.1` — breaking change для внешних подключений. Для удалённого доступа (claude.ai, Perplexity) используется cloudflared туннель, который биндится отдельно.

### 2.6 Аутентификация на /mcp

В отличие от SSE (`/messages/`), Streamable HTTP не разделяет соединение и сообщения — каждый запрос самостоятельный. `_check_auth` должен оставаться на `/mcp` endpoint.

Клиенты передают токен:
- Query param: `/mcp?token=<TOKEN>`
- Header: `Authorization: Bearer <TOKEN>`
- Header: `api-key: <TOKEN>`

Codex передаёт через `http_headers` в config.toml. Antigravity — через `headers` в mcp_config.json.

### 2.7 stateless=True

`StreamableHTTPSessionManager(stateless=True)` — оставить. В embedded режиме состояние хранится в conductor, event store не нужен.

### 2.8 Graceful shutdown

При `task.cancel()` из `conductor.stop()`:

```
1. conductor.stop() → http_task.cancel()
2. uvicorn получает сигнал завершения → начинает shutdown
3. Starlette lifespan выходит из yield → sm.run() context завершается
4. SM закрывает все активные сессии
5. http_task завершается
```

`conductor._http_task` устанавливается из `monitoring.py`:
```python
conductor._http_task = tg.create_task(http_run(...), name="mcp-http-server")
```

---

## 3. Изменения в коде

### 3.1 `src/mnemostroma/integration/mcp_http_adapter.py`

**Изменить `_make_mcp_server()`** — добавить параметр `conductor`:

```python
def _make_mcp_server(conductor=None) -> Server:
    srv = Server("mnemostroma")
    # НЕ переопределять create_initialization_options — убрать tools_changed=True

    @srv.list_tools()
    async def list_tools() -> list[Tool]:
        return [Tool(name=t["name"], description=t["description"],
                     inputSchema=t["inputSchema"]) for t in _TOOLS]

    @srv.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        try:
            if conductor is not None:
                from mnemostroma.ipc_server import _serialize
                raw = await conductor.dispatch(name, arguments)
                result = _serialize(raw)
            else:
                result = await safe_ipc_call(name, arguments)
            text = json.dumps(
                result if isinstance(result, (dict, list)) else {"result": result},
                default=str, ensure_ascii=False,
            )
            return [TextContent(type="text", text=text)]
        except Exception as exc:
            logger.error(f"call_tool {name!r} failed: {exc}", exc_info=True)
            return [TextContent(type="text", text=json.dumps({"error": str(exc)}))]

    return srv
```

**Изменить `lifespan` и `make_mcp_app()`** — принять `conductor`:

```python
def make_mcp_app(conductor=None):

    @asynccontextmanager
    async def lifespan(app):
        sm = StreamableHTTPSessionManager(
            app=_make_mcp_server(conductor=conductor),
            event_store=None,
            json_response=True,
            stateless=True,
        )
        async with sm.run():
            app.state.sm = sm
            yield

    return Starlette(
        debug=os.getenv("MNEMO_DEBUG", "false").lower() == "true",
        lifespan=lifespan,
        routes=[
            Route("/mcp",        endpoint=ASGIAppWrapper(handle_mcp),  methods=["GET", "POST", "DELETE"]),
            Route("/health",     endpoint=handle_health),
            Route("/mcp-config", endpoint=handle_mcp_config,           methods=["GET"]),
        ],
        middleware=[
            Middleware(PrivateNetworkAccessMiddleware),
            Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
        ]
    )
```

**Добавить `run()` для embedded режима:**

```python
async def run(
    conductor=None,
    port: int = 8768,
    host: str = "127.0.0.1",
    embedded: bool = True,
) -> None:
    config = uvicorn.Config(
        make_mcp_app(conductor=conductor),
        host=host,
        port=port,
        log_level="warning" if embedded else "info",
    )
    server = uvicorn.Server(config)
    logger.info("Embedded MCP HTTP server starting on %s:%s", host, port)
    await server.serve()
```

**`handle_health`** — добавить поддержку conductor:

```python
async def handle_health(request: Request):
    try:
        if hasattr(request.app.state, "conductor") and request.app.state.conductor:
            await request.app.state.conductor.dispatch("ctx_active", {})
        else:
            await safe_ipc_call("ctx_active", {})
        return JSONResponse({"status": "ok", "daemon": "connected", "mcpConfirmed": True})
    except Exception as e:
        return JSONResponse({"status": "error", "daemon": str(e)}, status_code=503)
```

Либо проще — оставить `safe_ipc_call` в health (некритично).

### 3.2 `src/mnemostroma/core/monitoring.py`

По аналогии с SSE — добавить HTTP task в TaskGroup:

```python
async def run_background_workers(conductor: "Conductor") -> None:
    async with asyncio.TaskGroup() as tg:
        logger.info("Starting background workers TaskGroup...")

        from mnemostroma.ipc_server import IPCServer
        ipc = IPCServer(conductor)
        tg.create_task(ipc.serve(), name="ipc_server")

        cfg = getattr(conductor, "config", {}) or {}

        # Embedded SSE server (legacy — для IntelliJ)
        sse_cfg = cfg.get("sse", {}) if isinstance(cfg, dict) else {}
        if sse_cfg.get("autostart", True):
            from mnemostroma.integration.mcp_sse_adapter import run as sse_run
            sse_task = tg.create_task(
                sse_run(conductor=conductor,
                        port=sse_cfg.get("port", 8765),
                        port_ext=sse_cfg.get("port_extension", 8766),
                        host=sse_cfg.get("host", "127.0.0.1")),
                name="mcp-sse-server",
            )
            conductor._sse_task = sse_task

        # Embedded HTTP server (Streamable HTTP — основной транспорт)
        http_cfg = cfg.get("http", {}) if isinstance(cfg, dict) else {}
        if http_cfg.get("autostart", True):
            from mnemostroma.integration.mcp_http_adapter import run as http_run
            http_task = tg.create_task(
                http_run(conductor=conductor,
                         port=http_cfg.get("port", 8768),
                         host=http_cfg.get("host", "127.0.0.1")),
                name="mcp-http-server",
            )
            conductor._http_task = http_task
            logger.info("Embedded MCP HTTP server scheduled on port %s", http_cfg.get("port", 8768))

        logger.info("Daemon is running. Press Ctrl+C to stop.")
        while True:
            await asyncio.sleep(86400)
```

### 3.3 `src/mnemostroma/conductor.py`

В начало `stop()` — остановить HTTP task первым:

```python
async def stop(self) -> None:
    self._stopping = True

    # Остановить HTTP сервер
    http_task = getattr(self, "_http_task", None)
    if http_task and not http_task.done():
        http_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(http_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # Остановить SSE сервер
    sse_task = getattr(self, "_sse_task", None)
    if sse_task and not sse_task.done():
        sse_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(sse_task), timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass

    # ... существующий shutdown sequence
```

### 3.4 `src/mnemostroma/cli/commands.py`

Команда `mnemostroma http` сохраняется для standalone/debug:

```python
elif command == "http":
    from mnemostroma.integration.mcp_http_adapter import run as http_run
    asyncio.run(http_run(conductor=None, embedded=False))
```

### 3.5 `config_default.json` / `~/.mnemostroma/config.json`

```json
{
  "sse": {
    "autostart": true,
    "port": 8765,
    "port_extension": 8766,
    "host": "127.0.0.1"
  },
  "http": {
    "autostart": true,
    "port": 8768,
    "host": "127.0.0.1"
  }
}
```

---

## 4. Systemd

### 4.1 `mnemostroma-http.service` — DEPRECATED

```python
units = (
    "mnemostroma-daemon.service",
    "mnemostroma-proxy.service",
    "mnemostroma-watchdog.service",
    "mnemostroma-ui.service",
    # "mnemostroma-sse.service",   # REMOVED: embedded in daemon
    # "mnemostroma-http.service",  # REMOVED: embedded in daemon
    "mnemostroma-tunnel.service",
)
```

В `mnemostroma-http.service` добавить заголовок:
```ini
# DEPRECATED: HTTP adapter is now embedded in mnemostroma-daemon.
# Use ONLY for standalone/debug: mnemostroma http
# To re-enable standalone: mnemostroma config set http.autostart false
#                           systemctl --user enable --now mnemostroma-http
```

### 4.2 Migration для существующих установок

Риск конфликта портов: если `mnemostroma-http.service` уже `enabled`:

```bash
systemctl --user disable --now mnemostroma-http.service 2>/dev/null || true
```

### 4.3 Watchdog

HTTP адаптер embedded — если daemon жив, HTTP скорее всего жив. Добавить TCP проверку порта 8768:

```python
async def _http_healthy(timeout: int = 2) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection("127.0.0.1", 8768), timeout=timeout)
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False
```

При `not _http_healthy()` — WARNING (не убивать daemon).

---

## 5. Клиентские конфиги

После деплоя все клиенты переключаются на Streamable HTTP:

**`~/.claude/mcp.json`** (Claude CLI):
```json
{
  "mcpServers": {
    "mnemostroma": {
      "type": "http",
      "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>"
    }
  }
}
```

**`~/.cursor/mcp.json`** (Cursor):
```json
{
  "mcpServers": {
    "mnemostroma": {
      "type": "http",
      "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>"
    }
  }
}
```

**`~/.config/Code/User/mcp.json`** (VS Code):
```json
{
  "servers": {
    "mnemostroma": {
      "type": "http",
      "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>"
    }
  }
}
```

**`~/.codex/config.toml`** (Codex):
```toml
[mcp_servers.mnemostroma]
url = "http://127.0.0.1:8768/mcp"

[mcp_servers.mnemostroma.http_headers]
Authorization = "Bearer <TOKEN>"
```

**`~/.gemini/antigravity/mcp_config.json`** (Antigravity):
```json
{
  "mcpServers": {
    "mnemostroma": {
      "serverUrl": "http://127.0.0.1:8768/mcp",
      "headers": {
        "Authorization": "Bearer <TOKEN>"
      }
    }
  }
}
```

**`~/.opencode/opencode.json`** (OpenCode):
```json
{
  "mcp": {
    "mnemostroma": {
      "type": "remote",
      "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>",
      "enabled": true
    }
  }
}
```

**`~/.qoder/mcp.json`** (Qoder):
```json
{
  "mcpServers": {
    "mnemostroma": {
      "type": "http",
      "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>"
    }
  }
}
```

> `<TOKEN>` = содержимое `~/.mnemostroma/sse_token`

---

## 6. Тесты

| ID | Что проверяет |
|----|--------------|
| TEST-HTTP-EMB-001 | HTTP сервер стартует внутри TaskGroup при `autostart: true` |
| TEST-HTTP-EMB-002 | HTTP сервер не стартует при `autostart: false` |
| TEST-HTTP-EMB-003 | `conductor.dispatch()` вызывается напрямую когда `conductor != None` |
| TEST-HTTP-EMB-004 | Fallback на `safe_ipc_call` когда `conductor=None` |
| TEST-HTTP-EMB-005 | `tools_changed` отсутствует в initialization capabilities |
| TEST-HTTP-EMB-006 | `conductor.stop()` отменяет HTTP task и ждёт завершения (timeout 5s) |
| TEST-HTTP-EMB-007 | Watchdog логирует WARNING при недоступном порту 8768 |
| TEST-HTTP-EMB-008 | Auth check: запрос без токена возвращает 401 |
| TEST-HTTP-EMB-009 | Auth check: токен в query param, Bearer header, api-key header — все принимаются |
| TEST-HTTP-EMB-010 | `mnemostroma http` запускает standalone режим с `conductor=None` |

---

## 7. Известные ограничения

- **Qoder** — формат конфига `mcp.json` не задокументирован официально; возможно потребует `"type": "sse"` как fallback. Проверить перед деплоем.
- **OpenCode** — использует `type: "remote"`, что может означать SSE или Streamable HTTP в зависимости от версии. Если не заработает — попробовать `type: "http"`.
- **Antigravity** — использует ключ `serverUrl` (не `url`). Это отличие от всех остальных клиентов.
- **Порт 8768 на `0.0.0.0`** в текущем коде — breaking change при изменении на `127.0.0.1` для внешних подключений через туннель. Туннель должен перебиндить на новый адрес.
