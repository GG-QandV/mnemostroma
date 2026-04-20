# Logging & Telemetry — Technical Reference
**Проект:** Mnemostroma v1.7.x  
**Применимость:** Только Repo A (Alpha / Private). В публичном Repo C этот модуль физически отсутствует.

---

## 1. Что это

Встроенная система телеметрии (`log_writer`) пишет диагностические события в SQLite-базу `logs.db`. Используется для:
- Профилирования задержек пайплайна (observer, search, NER, embed).
- Отслеживания аномалий (conflict, drift, высокая latency).
- Анализа роста базы и прогноза ёмкости (`mnemostroma growth`).
- Отладки при разработке и alpha-тестировании.

Данные пользователя не покидают локальную машину. `logs.db` — локальный SQLite-файл.

---

## 2. Где живёт

| Артефакт | Путь |
|----------|------|
| База телеметрии | `~/.mnemostroma/logs.db` |
| Рабочая база памяти | `~/.mnemostroma/mnemostroma.db` |
| Исходник логгера | `src/mnemostroma/storage/log_writer.py` |
| Конфиг логирования | `~/.mnemostroma/config.json` → секция `logging` |

---

## 3. Схема таблицы `onnx_logs`

```sql
CREATE TABLE onnx_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,   -- Unix timestamp в миллисекундах
    component   TEXT,               -- Компонент: "observer.pipe", "matrix.search", ...
    event       TEXT,               -- Тип события: "classify", "call", "evict", ...
    data        JSON,               -- Полезная нагрузка: параметры, счётчики, флаги
    latency_ms  REAL,               -- Задержка выполнения (мс)
    session_id  TEXT,               -- ID связанной сессии (если применимо)
    level       TEXT                -- "INFO" | "WARNING" | "ERROR"
);
-- Индексы: ts, component, session_id
```

---

## 4. Режимы логирования (`config.json`)

```json
{
  "logging": {
    "enabled": true,
    "mode": "safe",
    "db_path": "logs.db"
  }
}
```

| Режим | Что пишет |
|-------|-----------|
| `"safe"` | Только bootstrap, health, shutdown, все ERROR события |
| `"debug"` | Все события всех 23 компонентов |

Изменить во время работы:
```bash
mnemostroma config set logging.mode debug
mnemostroma off && mnemostroma on   # перезапуск обязателен
```

---

## 5. Компоненты и события (23 компонента)

| Component | Event | Что фиксирует |
|-----------|-------|---------------|
| `conductor.bootstrap` | `start` | Старт демона: `db_path`, `logs_path` |
| `conductor.health` | `check` | RAM (MB), `observer_alive` |
| `observer.pipe` | `ner+embed` | Кол-во сущностей NER, размер вектора, задержка |
| `observer.marker` | `classify` | Тип якоря, важность, тип сессии |
| `observer.score` | `calculate` | Breakdown: relevance/temporal/importance |
| `observer.anchor` | `create` | ID якоря, тип, кол-во key_facts |
| `observer.save` | `persist` | Теги, слой (RAM_HOT), задержка |
| `tuner.conflict` | `check` | Обнаружен конфликт (bool), флаги |
| `tuner.conflict` | `error` | Исключение при проверке конфликта |
| `tuner.drift` | `check` | Оценка семантического дрейфа |
| `matrix.search` | `query` | Размер вектора запроса, top_k, задержка |
| `reranker.rerank` | `rerank` | Кандидаты вход/выход, задержка |
| `dissolver.evict` | `evict` | ID вытесненной сессии, score, причина |
| `consolidation.recalc` | `batch` | Сессий проверено, duration_ms |
| `anchor.decay` | `batch` | Якоря деградированы, threshold_days |
| `storage.flush` | `batch` | flushed_count, queue_depth |
| `dreamer.cycle` | `complete` | Статистика Dreamer (anchors reassessed) |
| `tools.semantic` | `call` | Запрос, кол-во результатов, задержка |
| `tools.search` | `call` | Теги, кол-во результатов |
| `tools.anchors` | `call` | Тип якоря, кол-во результатов |
| `tools.active` | `call` | Размер снимка активных сессий |
| `feedback.implicit` | `signal` | Тип сигнала (USE/IGNORE/REVISIT) |
| `experience.signal` | `fire` | Тип интуиции, тег, maturity, avg_score |

---

## 6. Готовые SQL-запросы для диагностики

```sql
-- Все события за последний час
SELECT datetime(ts/1000, 'unixepoch', 'localtime'), component, event, latency_ms, data
FROM onnx_logs WHERE ts > (strftime('%s','now') - 3600) * 1000 ORDER BY ts DESC;

-- Только ERROR уровень
SELECT datetime(ts/1000, 'unixepoch', 'localtime'), component, event, data
FROM onnx_logs WHERE level = 'ERROR' ORDER BY ts DESC;

-- Средняя задержка по компонентам
SELECT component, event, round(avg(latency_ms), 2) as avg_ms, round(max(latency_ms), 2) as max_ms, count(*) as calls
FROM onnx_logs GROUP BY component, event ORDER BY avg_ms DESC;

-- Обнаруженные конфликты с якорями
SELECT datetime(ts/1000, 'unixepoch', 'localtime'), data, session_id
FROM onnx_logs WHERE component = 'tuner.conflict' AND event = 'check'
  AND json_extract(data, '$.detected') = 1;

-- Медленные операции (>100ms)
SELECT datetime(ts/1000, 'unixepoch', 'localtime'), component, event, latency_ms, session_id
FROM onnx_logs WHERE latency_ms > 100 ORDER BY latency_ms DESC LIMIT 50;

-- Пропускная способность Observer'а (события в минуту)
SELECT strftime('%H:%M', ts/1000, 'unixepoch') as minute, count(*) as events
FROM onnx_logs WHERE component LIKE 'observer.%'
GROUP BY minute ORDER BY minute DESC LIMIT 30;

-- Вытеснения памяти (Dissolver activity)
SELECT datetime(ts/1000, 'unixepoch', 'localtime'), json_extract(data, '$.session_id') as sid,
       json_extract(data, '$.reason') as reason
FROM onnx_logs WHERE component = 'dissolver.evict' ORDER BY ts DESC LIMIT 20;

-- Все события конкретной сессии
SELECT datetime(ts/1000, 'unixepoch', 'localtime'), component, event, data
FROM onnx_logs WHERE session_id = '<your-session-id>' ORDER BY ts;
```

Выполнить из Python (sqlite3 не установлен системно):
```bash
/home/gg/.mnemostroma/venv/bin/python3 -c "
import sqlite3
conn = sqlite3.connect('/home/gg/.mnemostroma/logs.db')
cur = conn.cursor()
cur.execute('SELECT component, event, round(avg(latency_ms),2), count(*) FROM onnx_logs GROUP BY component, event ORDER BY 3 DESC')
for r in cur.fetchall(): print(r)
"
```

---

## 7. Как отключить логирование

### Временно (без перезапуска — не поддерживается, нужен рестарт):
```bash
mnemostroma config set logging.enabled false
mnemostroma off && mnemostroma on
```

### Полностью удалить базу телеметрии:
```bash
mnemostroma off
rm ~/.mnemostroma/logs.db
mnemostroma on    # logs.db будет пересоздана с нуля при следующем старте
```

---

## 8. Как удалить для чистой (публичной) версии

Система логирования **физически изолирована** от публичного кода через git-hook и модульную структуру:

**Что НЕ попадает в публичный репозиторий (Repo C):**
- `src/mnemostroma/storage/log_writer.py`
- Вызовы `await log_event(...)` во всех файлах
- Секция `logging` в `config_default.json`
- Таблица `onnx_logs` не создаётся в публичной версии

**Автоматическая защита через pre-commit hook:**
```bash
# .git/hooks/pre-commit проверяет наличие следов логирования
grep -rn "await log_event(" src/ --include="*.py"
grep -rn "from mnemostroma.storage.logwriter" src/ --include="*.py"
grep -rn "onnxlogs\|logs\.db" src/ --include="*.py"
# При обнаружении — блокирует коммит
```

**Если нужно вручную вырезать логирование для нового форка:**
1. Удалить `src/mnemostroma/storage/log_writer.py`
2. Убрать `from ..storage.log_writer import log_event` из всех файлов `src/`
3. Заменить все вызовы `await log_event(ctx, ...)` на `pass`
4. Удалить секцию `"logging"` из `config_default.json`
5. Проверить: `grep -rn "log_event\|logwriter\|logs\.db" src/`

---

## 9. Таблица `db_snapshots` (Repo A, v2 — запланировано)

> Статус: **Запланировано** (Задача 3B плана `TASK_growth_flash_agent.md`)

Будет добавлена в `logs.db` для точного прогнозирования роста:

```sql
CREATE TABLE IF NOT EXISTS db_snapshots (
    ts           INTEGER NOT NULL,     -- Unix timestamp снимка
    db_size_mb   REAL,                 -- Размер mnemostroma.db в MB
    logs_size_mb REAL                  -- Размер logs.db в MB
);
```

Писать из `ConsolidationWorker` раз в час. Использовать как исторический ряд для модели `GrowthForecast` (линейная + экспоненциальная экстраполяция).

---

## 10. Известные ограничения

| Ограничение | Статус |
|-------------|--------|
| `mnemostroma logs --days N` зависает с `ModuleNotFoundError` | Баг — модуль `mnemostroma.tools.logs` отсутствует в production-пакете |
| `mnemostroma watch` — та же ошибка | Баг — `mnemostroma.tools.watch` отсутствует |
| `test_observer.py` и `test_reranker_integration.py` зависают при `pytest tests/` | Грузят реальные ONNX-модели при запущенном демоне — конфликт GIL/ресурсов |
| Прогноз роста не учитывает `logs.db` | Задача 1 плана `TASK_growth_flash_agent.md` — в работе |
| Только линейная экстраполяция | Задача 2 — класс `GrowthForecast` запланирован |
