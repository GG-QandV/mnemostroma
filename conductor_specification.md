# Conductor — Спецификация
## RAM-First Context System v1.7.1
> Обновлено: 2026-04-07 | Phase 9.2 Complete

---

## 1. Роль

Conductor — точка входа и оркестратор всей системы. 
Он отвечает за: bootstrap, event loop, health check, routing, RAM budget и управление слоем персистентности (PersistenceLayer).

---

## 2. Deployment Modes (v1.7.1)

### Mode 1: User Mode (CLI-based)
```bash
mnemostroma setup   # Шаг 0: модели + дефолтный конфиг в ~/.mnemostroma/
mnemostroma on      # Шаг 1: запуск фонового демона
mnemostroma status  # Шаг 2: проверка через инструмент API
```

### Mode 2: Embedded Library (SDK)
```python
from mnemostroma import ctx
bridge = ctx.active()  # Автоматический bootstrap при первом импорте
```

---

## 3. Bootstrap — 10 шагов холодного старта (v1.7.1)

```python
async def bootstrap(config: dict):
    # Шаг 1: Загрузить Config (80+ параметров)
    # Шаг 2: Инициализировать PersistenceLayer (Phase 9.2)
    persistence = PersistenceLayer(config.db_path)
    await persistence.connect()

    # Шаг 3: Lazy Load моделей (multilingual-e5-small + DistilBERT NER)
    models = ModelRegistry(config)

    # Шаг 4: Построить MatrixSearch из SQLite embeddings (dim=384)
    # (полный граф смыслов перестраивается в RAM для скорости)
    session_index = await persistence.build_matrix_search(dim=384)

    # Шаг 5: Загрузить RAM Hot/Warm сессии (Top-N по Score)
    ram_dict = await persistence.load_hot_sessions(limit=config.window_size)

    # Шаг 6: Запустить Observer Pipeline
    observer = Observer(models, persistence, ram_dict)

    # Шаг 7: Запустить Subconscious Workers (Stage C/D)
    decay_engine = DecayEngine(config, persistence)
    dreamer = Dreamer(config, persistence)

    # Шаг 8: Запустить Health Check Loop
    health_task = asyncio.create_task(health_loop(persistence, ram_dict))

    # Шаг 9: Запустить Consolidation Worker (Phase 9.2: await writes)
    # Шаг 10: Готово
    return SystemContext(persistence, models, session_index, ram_dict)
```

---

## 4. RAM Budget Management

| Компонент | RAM (RSS) |
|-----------|-----------|
| E5-small ONNX | ~420MB |
| HybridNER ONNX | ~170MB |
| TinyBERT Reranker | 8MB (lazy) |
| **Базовая нагрузка** | **~603MB** |
| Данные (Top-200) | ~30MB |
| **ИТОГО (v1.7.1)** | **~631MB** |

---

## 5. Graceful Shutdown (v1.7.1)

1. **Wait for Persistence**: Дождаться завершения всех `await ctx.persistence` вызовов.
2. **Flush Session Queue**: Сбросить очередь `enqueue_session` (max 5s).
3. **Checkpoint WAL**: `PRAGMA wal_checkpoint(TRUNCATE)`.
4. **Close Persistence**: Закрыть дескрипторы SQLite.

---

*Mnemostroma | Conductor Specification | v1.7.1 | 2026-04-07*
*μνήμη + στρῶма · 303 tests · stable*
