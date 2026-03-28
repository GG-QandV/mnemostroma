# Conductor — Спецификация
## RAM-First Context System v1.0

---

## 1. Роль

Conductor — точка входа и оркестратор всей системы.
Он отвечает за: bootstrap, event loop, health check, routing, RAM budget.

Без Conductor система не стартует. Все остальные компоненты (Observer, Dissolver, Tuner, Content Branch) запускаются и останавливаются через него.

---

## 2. Четыре Deployment Modes

### Mode 1: Embedded Library
```python
# Агент просто импортирует — Observer запускается автоматически
from context_system import ctx, content

bridge = ctx.active()  # система уже работает
```
- Observer как `asyncio.create_task()` внутри процесса агента
- Никакого демона, никакого IPC
- Подходит для: Claude API, OpenAI Agents, любой Python-агент

### Mode 2: Local Daemon + IPC
```
┌─────────────┐   Unix Socket / Named Pipe   ┌──────────────────┐
│  VS Code    │ ─────────────────────────── │  context-daemon  │
│  Cursor     │   JSON-RPC 2.0 (как LSP)    │  port: 47821     │
│  Terminal   │                              │  SQLite + ONNX   │
└─────────────┘                              └──────────────────┘
```
- Один демон на машину, все клиенты подключаются к нему
- Протокол: JSON-RPC 2.0 (тот же что LSP)
- Подходит для: IDE extensions, терминальные агенты

### Mode 3: CLI Tool
```bash
ctx status                    # ctx.status() дашборд
ctx search "#JWT"             # поиск по тегам
ctx semantic "авторизация"    # семантический поиск
ctx bridge                    # session bridge
ctx daemon start              # запустить демон
ctx daemon stop               # остановить
ctx daemon status             # проверить
```

### Mode 4: Local + Cloud Sync (опциональный)
```python
# В config.json
{
  "cloud_sync": {
    "enabled": true,
    "endpoint": "https://sync.example.com",
    "layers": ["SQLite_Archive", "SQLite_Eternal"],  // только холодные
    "interval_sec": 300,
    "encrypted": true
  }
}
```
- Синхронизируются ТОЛЬКО холодные слои (Archive + Eternal)
- RAM Hot/Warm никогда не покидают машину
- Latency основной системы не затрагивается

---

## 3. Bootstrap — 10 шагов холодного старта

```python
async def bootstrap(config: dict):

    # Шаг 1: Загрузить конфиг
    config = load_config("~/.context/config.json")

    # Шаг 2: Загрузить ONNX-модели в RAM (~10-15 сек, ~342MB)
    models = await load_models(config["models_path"])
    # EmbeddingGemma + BGE-M3 + TinyBERT + GLiNER

    # Шаг 3: Открыть SQLite WAL
    db = open_sqlite(config["db_path"])
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA synchronous=NORMAL")
    db.execute("PRAGMA cache_size=-64000")    # 64MB
    db.execute("PRAGMA mmap_size=268435456")  # 256MB

    # Шаг 4: Перестроить Session HNSWlib из ВСЕХ embeddings
    # (полный граф смыслов — даже для архивных сессий)
    session_hnsw = build_hnsw_from_all_embeddings(db)

    # Шаг 5: Загрузить Content HNSWlib
    if os.path.exists(config["content_hnsw_path"]):
        content_hnsw = load_hnsw(config["content_hnsw_path"])
    else:
        content_hnsw = build_hnsw_from_content_versions(db)

    # Шаг 6: Загрузить последние N сессий в RAM по Score
    # N = адаптивный (дефолт 200, ограничен soft_limit RAM)
    ram_index = load_top_sessions_by_score(db, n=config["window_default"])

    # Шаг 7: Запустить Dissolver.recalc для всех загруженных сессий
    for sid in ram_index:
        new_res = dissolver.recalc(ram_index[sid], config)
        dissolver.apply_layer(sid, new_res, ram_index, db)

    # Шаг 8: Запустить Observer coroutine
    observer_task = asyncio.create_task(observer_loop(models, db, ram_index))

    # Шаг 9: Запустить Consolidation Worker
    consolidation_task = asyncio.create_task(consolidation_worker(ram_index, db))

    # Шаг 10: Готово
    log.info(f"Bootstrap complete. RAM: {get_ram_mb()}MB, "
             f"Sessions: {len(ram_index)}, "
             f"HNSWlib: {session_hnsw.get_current_count()} vectors")
    return SystemContext(models, db, ram_index, session_hnsw, content_hnsw)
```

---

## 4. Event Loop

```python
async def event_loop(sys_ctx: SystemContext):
    while True:
        # Слушаем события от всех компонентов
        event = await sys_ctx.event_queue.get()

        if event.type == "agent_output":
            # → Observer
            asyncio.create_task(observer_process(event.data, sys_ctx))

        elif event.type == "content_save":
            # → Content Branch
            asyncio.create_task(content_save(event.data, sys_ctx))

        elif event.type == "ram_pressure":
            # → Dissolver eviction
            asyncio.create_task(dissolver.emergency_evict(sys_ctx))

        elif event.type == "shutdown":
            await graceful_shutdown(sys_ctx)
            break
```

---

## 5. Health Check

```python
async def health_check(sys_ctx: SystemContext):
    while True:
        await asyncio.sleep(30)

        issues = []

        # Observer живой?
        if sys_ctx.observer_last_ping < time.time() - 60:
            issues.append("Observer не отвечает >60s")
            asyncio.create_task(restart_observer(sys_ctx))

        # RAM в норме?
        ram_mb = get_ram_mb()
        if ram_mb > CONFIG["ram_hard_limit_mb"]:
            issues.append(f"RAM критический: {ram_mb}MB")
            await dissolver.emergency_evict(sys_ctx)

        # SQLite WAL не разбух?
        wal_size = get_wal_size_mb(sys_ctx.db_path)
        if wal_size > 50:
            issues.append(f"WAL большой: {wal_size}MB")
            sys_ctx.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        # SQLite рост > budget?
        if sys_ctx.growth_today_mb > CONFIG["db_growth_budget_mb_per_day"]:
            issues.append(f"Рост DB > budget: {sys_ctx.growth_today_mb}MB/day")

        if issues:
            log.warning("Health issues: " + "; ".join(issues))
```

---

## 6. RAM Budget Management

```python
RAM_CONFIG = {
    "models_fixed_mb":        342,   # фиксированно
    "ram_soft_limit_mb":      380,   # плановый evict данных
    "ram_hard_limit_mb":      480,   # экстренный evict
    "window_default":         200,   # дефолт сессий в RAM
    "window_min":              50,   # абсолютный минимум
    "total_budget_mb":        600,   # целевой потолок
}

# Адаптивный размер окна
def calc_window_size(available_ram_mb: float) -> int:
    data_budget = available_ram_mb - RAM_CONFIG["models_fixed_mb"]
    # ~1MB на сессию (brief + anchors + precision + vector)
    window = int(data_budget / 1.0)
    return max(RAM_CONFIG["window_min"],
               min(window, RAM_CONFIG["window_default"]))
```

---

## 7. Структура папки на машине

```
~/.context/
├── models/
│   ├── embeddinggemma-300m.onnx      52MB
│   ├── bge-m3.onnx                  145MB
│   ├── tinybert-l2.onnx               8MB
│   └── gliner-small.onnx             42MB
├── data/
│   ├── context.db                    SQLite WAL (основная БД)
│   └── content_hnsw.bin              персистентный Content индекс
├── config.json                       конфигурация
├── daemon.pid                        PID если демон запущен
└── daemon.log                        лог демона
```

---

## 8. Установка

### Вариант А: Python (для разработчиков)
```bash
pip install context-memory
# или
uv add context-memory

# Первый запуск — скачает модели (~342MB)
ctx daemon start
```

### Вариант Б: Бинарник (для всех, Python не нужен)
```bash
# Скачать архив (~380MB со всеми моделями)
# Linux:
wget context-memory-v1.0-linux-x86_64.tar.gz
tar xf context-memory-v1.0-linux-x86_64.tar.gz
./ctx daemon start

# macOS:
brew install context-memory  # или .pkg установщик

# Windows:
# context-memory-v1.0-windows-x64.zip → распаковать → ctx.exe daemon start
```
Собирается через PyInstaller / Nuitka в единый бинарник.

---

## 9. IDE интеграция (по модели LSP)

```json
// .vscode/settings.json
{
  "context-memory.daemon": "auto",
  "context-memory.db": "~/.context/data/context.db",
  "context-memory.models": "~/.context/models/",
  "context-memory.port": 47821
}
```

Extension делает одно: при старте IDE запускает `ctx daemon start` если не запущен. Общение через JSON-RPC 2.0 по Unix Socket (macOS/Linux) или Named Pipe (Windows).

---

## 10. Платформы

| Платформа | IPC механизм | Статус |
|---|---|---|
| Linux | Unix Socket | ✅ |
| macOS | Unix Socket | ✅ |
| Windows | Named Pipe | ✅ |
| Docker | volume mount + embedded | ✅ |
| Android | Python + ONNX Runtime Android | 🟡 Phase 3 |
| iOS | Swift + ONNX Runtime iOS SDK | 🟡 Phase 3 (отдельная кодовая база) |

---

## 11. Graceful Shutdown

```python
async def graceful_shutdown(sys_ctx: SystemContext):
    # 1. Остановить Observer
    sys_ctx.observer_task.cancel()

    # 2. Flush все pending SQLite операции
    await flush_all_pending(sys_ctx.db)

    # 3. Сохранить content_hnsw.bin
    sys_ctx.content_hnsw.save_index(CONFIG["content_hnsw_path"])

    # 4. Session HNSWlib НЕ сохраняем — перестраивается из SQLite при старте

    # 5. Закрыть SQLite
    sys_ctx.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    sys_ctx.db.close()

    log.info("Shutdown complete")
```
