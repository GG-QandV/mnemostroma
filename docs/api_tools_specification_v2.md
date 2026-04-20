# API инструментов — Дополнение v1.1
## RAM-First Context System

Это дополнение к `api_tools_specification.md`.
Добавляет три новых инструмента мониторинга.

---

## ctx.status() — расширенный дашборд

Возвращает полную картину состояния системы. Latency: <5ms (только RAM + os stats).

```python
ctx.status() -> str  # ASCII дашборд
```

```
╔══════════════════════════════════════════════════╗
║  RAM-First Context System — Status               ║
╠══════════════════════════════════════════════════╣
║  RAM                                             ║
║  Models:      342MB  ████████░░░░░░░  (57%)     ║
║  Session RAM: 187MB  █████░░░░░░░░░░  (31%)     ║
║  Content RAM:   4MB  ░░░░░░░░░░░░░░░  ( 1%)     ║
║  TOTAL:       533MB  ██████████████░  (89%) ⚠️  ║
╠══════════════════════════════════════════════════╣
║  Сессии                                          ║
║  RAM Hot:      142   SQLite Deep:    1 204       ║
║  RAM Warm:      58   SQLite Archive: 8 901       ║
║  SQLite Total: 10 305   Eternal:       200       ║
╠══════════════════════════════════════════════════╣
║  SQLite (context.db)                             ║
║  Размер файла:  284MB   Рост сегодня: +1.2MB    ║
║  WAL pending:     3     Last flush:   0.3s ago  ║
╠══════════════════════════════════════════════════╣
║  Latency (p50/p95)                               ║
║  ctx.active():   0.01ms / 0.02ms                ║
║  ctx.semantic(): 18ms   / 24ms                  ║
║  Observer write: 21ms   / 31ms                  ║
╠══════════════════════════════════════════════════╣
║  HNSWlib                                         ║
║  Session index: 10 305 vectors   4.2MB          ║
║  Content index:  2 847 vectors   1.1MB          ║
╚══════════════════════════════════════════════════╝
```

Структура возвращаемого dict (для программного использования):
```python
{
    "ram": {
        "models_mb": 342, "sessions_mb": 187,
        "content_mb": 4,  "total_mb": 533,
        "total_pct": 89,  "warning": True,
    },
    "sessions": {
        "ram_hot": 142, "ram_warm": 58,
        "sqlite_deep": 1204, "sqlite_archive": 8901,
        "sqlite_eternal": 200, "total": 10305,
    },
    "sqlite": {
        "size_mb": 284, "growth_today_mb": 1.2,
        "wal_pending": 3, "last_flush_sec": 0.3,
    },
    "latency_p50": {"active_ms": 0.01, "semantic_ms": 18, "observer_ms": 21},
    "latency_p95": {"active_ms": 0.02, "semantic_ms": 24, "observer_ms": 31},
    "hnsw": {"session_vectors": 10305, "content_vectors": 2847},
}
```

---

## ctx.growth() — рост данных

Анализ роста и прогноз исчерпания. Latency: <10ms (SQLite aggregate queries).

```python
ctx.growth() -> dict
```

Вывод:
```
╔════════════════════════════════════════╗
║  Growth Report                         ║
╠════════════════════════════════════════╣
║  Сессии:   10 305 total                ║
║  Сегодня:     +12    за неделю:  +84  ║
║  За месяц:   +310    за год:  +3 204  ║
╠════════════════════════════════════════╣
║  SQLite размер:  284MB                 ║
║  Рост/день:     ~1.2MB                 ║
║  До 1GB:        ~595 дней             ║
║  До 10GB:       ~8 лет                ║
╠════════════════════════════════════════╣
║  Embeddings (HNSWlib):                 ║
║  Session:  10 305 × 512d = 10.5MB     ║
║  Content:   2 847 × 512d =  2.9MB     ║
║  Рост/год:  ~3 200 × 512d = +3.3MB   ║
╚════════════════════════════════════════╝
```

```python
{
    "sessions_total": 10305,
    "sessions_today": 12,
    "sessions_week": 84,
    "sessions_month": 310,
    "sessions_year": 3204,
    "db_size_mb": 284,
    "db_growth_per_day_mb": 1.2,
    "days_to_1gb": 595,
    "days_to_10gb": 8 * 365,
    "hnsw_session_mb": 10.5,
    "hnsw_content_mb": 2.9,
    "hnsw_growth_per_year_mb": 3.3,
}
```

---

## ctx.pulse() — живой счётчик

Минимальный статус для логов и статус-баров. Latency: <0.01ms (только RAM dict).

```python
ctx.pulse() -> dict
```

```python
{"sessions": 10305, "ram_mb": 533, "ram_pct": 89, "db_mb": 284, "latency_ms": 18}
```

Строка для логов:
```
[CTX] 10305 sess | RAM 533MB (89%) | DB 284MB | latency 18ms
```

Использование:
```python
# В логах агента
log.info(ctx.pulse_str())   # однострочный формат

# В статус-баре IDE
pulse = ctx.pulse()
status_bar.update(f"CTX {pulse['ram_pct']}% | {pulse['sessions']} sess")
```
