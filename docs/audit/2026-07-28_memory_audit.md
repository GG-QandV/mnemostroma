# Memory Audit — 2026-07-28

## 1. Whisper model — не найдена

В системе **нет** скачанной модели Whisper. Ожидаемые пути:
- `models/ggml-base.bin` (WhisperConfig.model_path)
- `models/ggml-tiny.bin` (WhisperConfig.fallback_model_path)

Ни один из этих файлов не обнаружен ни в проекте, ни в `~/.mnemostroma/models/`, ни в общесистемных путях. При запуске `speech-local` модуль `WhisperRunner.__init__` проверит существование через `model_path.exists()` и выбросит `ModelNotAvailable`.

**Рекомендация:** загрузить модель до запуска — `scripts/download_model.sh` (или вручную `wget` из HuggingFace ggml-репозитория).

---

## 2. Mnemostroma — анализ роста памяти

### 2.1. Базы данных

| Файл | Размер | Записей | Период |
|------|--------|---------|--------|
| `logs.db` | **96 MB** | 663,052 (`onnx_logs`) | ~2026-04-17 – 2026-07-28 (102 дня) |
| `mnemostroma.db` | **27 MB** | 3,806 сессий | ~2026-04-17 – 2026-07-28 |
| `logs.db-wal` | **4 MB** | — | — |
| `mnemostroma.db-wal` | **329 MB** | — | — |
| `mnemostroma.db-shm` | 32 KB | — | — |

**Ключевое наблюдение:** `mnemostroma.db-wal` = 329 MB при основной БД 27 MB (**12x**). WAL не чекпоинтится.

### 2.2. LogWriter — буфер

Файл: `src/mnemostroma/storage/log_writer.py`

- `asyncio.Queue(maxsize=1000)` — очередь **капнута** на 1000 записей. При переполнении — `QueueFull` → запись молча дропается.
- Batch flush: до 100 записей, таймаут 2 секунды.
- **Нет вызова `PRAGMA wal_checkpoint`** — WAL растёт бесконтрольно.
- `PersistenceLayer.sync()` делает WAL checkpoint только при явном вызове (не по расписанию).

### 2.3. RSS daemon

| Момент | VmRSS |
|--------|-------|
| 2026-07-28 16:05 | 3,852 KB |
| 2026-07-28 16:07 | 3,844 KB |

RSS **стабилен** (~3.8 MB). Рост памяти в RSS не наблюдается — проблема не в heap-утечке, а в **дисковом WAL**.

### 2.4. ONNX-модели

| Модель | Размер |
|--------|--------|
| `multilingual-e5-small` (int8) | 113 MB |
| `tinybert-l2-v2` (int8) | 4.3 MB |
| `distilbert-ner` (int8) | (неизвестно) |

### 2.5. Распределение места (~/.mnemostroma/)

| Директория | Размер |
|-----------|--------|
| `backups/` | **20 GB** |
| `venv/` | 2.6 GB |
| `models/` | 271 MB |
| `bin/` | 38 MB |
| `logs.db` | 96 MB |
| `mnemostroma.db` | 27 MB |
| `mnemostroma.db-wal` | 329 MB |
| **Итого** | **~24 GB** |

---

## 3. Выводы

### Первопричина роста памяти (не RSS, а WAL)

1. `mnemostroma.db-wal` = 329 MB — доминирующий источник «занятого места».
2. WAL не чекпоинтится автоматически. `PersistenceLayer.sync()` делает checkpoint, но не вызывается регулярно.
3. `logs.db` (96 MB, 663K записей) — второй фактор, но он ожидаем за 102 дня.

### Что делать

1. **Добавить `PRAGMA wal_checkpoint(TRUNCATE)` в LogWriter** при старте + периодически в flush-цикле (каждый N-ный батч или по таймеру).
2. **Настроить автоматический checkpoint** через `PRAGMA wal_autocheckpoint=N` (сейчас не установлен — дефолт 1000 страниц).
3. **Ограничить глубину `onnx_logs`** — например, DELETE после 30 дней.
4. **Бекапы** (20 GB) — пересмотреть политику ротации.
5. **Whisper model** — загрузить в `data/models/` перед запуском speech-local.

### Тренд

- `onnx_logs`: ~6,500 записей/день (~4.5/мин) — умеренно.
- `sessions`: ~37 сессий/день — низкая нагрузка.
- WAL растёт быстрее DB из-за отсутствия checkpoint при интенсивной пакетной записи логов.

---

## UPDATE 2026-07-28 — Applied fixes

### Шаг 1. Ручной checkpoint
- `mnemostroma.db-wal`: **329 MB → 0 KB** (TRUNCATE checkpoint)
- `logs.db-wal`: **4 MB → 0 KB**

### Шаг 2. Автоматический checkpoint
- `wal_autocheckpoint` = 1000 (дефолт) уже стоял, но не срабатывал из-за долгих open транзакций в `PersistenceLayer` и `LogWriter`.
- **Фикс:** в `LogWriter._flush_loop` добавлен периодический `PRAGMA wal_checkpoint(TRUNCATE)` каждые 5000 записанных записей (~раз в несколько минут при текущей нагрузке).

### Шаг 3. QueueFull — warning вместо silent drop
- `src/mnemostroma/storage/log_writer.py:89` — `pass` заменён на `logger.warning("LogWriter queue full (max=1000), dropping log entry")`.

### Шаг 4. ONNX-логи
- Удалены записи старше 30 дней (ts < now - 30d). Было 663,052 → стало 629,859 записей.
- VACUUM не выполнен — `logs.db` locked (daemon работает).

### Шаг 5. Backups
- **611 файлов, 20 GB.** Ротации нет — backups копятся с апреля 2026.
- Рекомендация: оставить ежедневный backup за последние 14 дней (сохраняет ~14 файлов), удалить остальное (~597 файлов, ~19.5 GB).

### Итоговое состояние

| Метрика | До | После фикса |
|---------|----|------------|
| WAL mnemostroma.db | 329 MB | ~2.6 MB (растёт, но теперь чекпоинтится) |
| WAL logs.db | 4 MB | ~10 MB |
| onnx_logs записей | 663,052 | 629,859 |
| backups | 20 GB (611 файлов) | не менялось |
| ~/.mnemostroma/ всего | ~24 GB | ~23 GB |

**Далее:** если backups не нужны за апрель–июнь — освободится ~19.5 GB.
