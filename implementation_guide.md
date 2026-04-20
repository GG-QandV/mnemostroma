# Mnemostroma — Implementation Guide
> Порядок реализации от скелета до полной системы
> 2026-03-25

---

## Принцип

27 файлов спецификаций описывают ЧТО система делает.
Этот гайд описывает В КАКОМ ПОРЯДКЕ это кодить.

Правило: каждый шаг = запускаемый и тестируемый компонент.
Не переходить к следующему пока текущий не работает.

---

## Фаза 0: Скелет проекта

### Структура директорий

```
mnemostroma/
├── mnemostroma/
│   ├── __init__.py          # from .core import ctx, content
│   ├── core.py              # Conductor + глобальные ctx/content объекты
│   ├── config.py            # ConfigLoader → config.json → dict
│   ├── observer/
│   │   ├── __init__.py
│   │   ├── pipeline.py      # Observer async pipeline
│   │   ├── filter.py        # Детерминированный фильтр
│   │   ├── ner.py           # GLiNER wrapper
│   │   └── embedder.py      # EmbeddingGemma wrapper
│   ├── memory/
│   │   ├── __init__.py
│   │   ├── session_index.py # RAM dict + операции
│   │   ├── hnsw.py          # HNSWlib wrapper
│   │   ├── anchors.py       # Anchor Layer
│   │   └── precision.py     # Precision Log
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── sqlite.py        # SQLite WAL connection + async flush
│   │   └── schemas.py       # CREATE TABLE + migrations
│   ├── dissolver/
│   │   ├── __init__.py
│   │   └── dissolver.py     # recalc + apply_layer + eviction
│   ├── tuner/
│   │   ├── __init__.py
│   │   └── conflict.py      # Conflict Detector (первый, остальные позже)
│   ├── content/
│   │   ├── __init__.py
│   │   └── branch.py        # Content blocks + versions
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── read.py          # ctx.active/get/search/semantic/bridge
│   │   ├── write.py         # ctx.save/update/flag + content.save/tag
│   │   └── admin.py         # ctx.sync/load/status/pulse/configure
│   └── feedback/
│       ├── __init__.py
│       └── implicit.py      # USE/DEEP_USE/IGNORE/REVISIT signals
├── models/                   # ONNX INT8 модели (не в git, скачиваются)
│   ├── embeddinggemma-300m-int8/
│   ├── bge-m3-int8/
│   ├── gliner-small-v2.1-int8/
│   └── tinybert-l2-v2-int8/
├── config.json               # Дефолтная конфигурация (80 параметров)
├── tests/
├── README.md
└── pyproject.toml
```

### Зависимости (pyproject.toml)

```toml
[project]
dependencies = [
    "onnxruntime>=1.17",
    "tokenizers>=0.15",
    "numpy>=1.24",
    "hnswlib>=0.8",
    "lz4>=4.0",
]
```

Всё. Шесть пакетов. Без torch, transformers, langchain.

### Что проверить

```bash
python -c "from mnemostroma import ctx; print(ctx)"
# Должно: загрузить config, инициализировать пустой объект
```

---

## Фаза 1: Observer + Session Index (минимальная петля записи)

### Шаг 1.1: Config + SQLite

**Файлы:** `config.py`, `storage/sqlite.py`, `storage/schemas.py`

- Загрузить config.json → dict
- Создать SQLite WAL connection
- Выполнить CREATE TABLE (sessions, anchors, precision_log)
- async flush queue (asyncio.Queue + writer coroutine)

**Тест:** записать и прочитать одну сессию через SQL.

**Спеки:** `config_tuner_v1.0.md`, `architecture_overview.md` секция 7 (SQLite schema)

### Шаг 1.2: EmbeddingGemma + HNSWlib

**Файлы:** `observer/embedder.py`, `memory/hnsw.py`

- Загрузить EmbeddingGemma ONNX
- encode(text) → float16[512]
- Создать HNSWlib index (M=16, ef_construction=200)
- add_items, knn_query

**Тест:** embed два текста, проверить cosine similarity > 0.7 для похожих.

**Спеки:** `stack_specification.md`, `embedding_chain_v1.3.md`

### Шаг 1.3: Детерминированный фильтр

**Файлы:** `observer/filter.py`

- IMPORTANCE_SIGNALS regex
- detect_urgency(), detect_principle()
- Precision detection (URL, phone, email, numbers)
- Возврат: {importance, urgency, precision_items, anchor_items, needs_ner}

**Тест:** 10 тестовых фрагментов → проверить importance classification.

**Спеки:** `observer_specification_v1.3.md` секция 3, `architecture_overview.md` секция 5.2

### Шаг 1.4: Observer pipeline (без GLiNER)

**Файлы:** `observer/pipeline.py`, `memory/session_index.py`

- Подключить фильтр → embedder → Score → RAM dict
- async flush → SQLite через очередь
- Пока БЕЗ GLiNER — только детерм. фильтр + embedding

**Тест:** подать 10 сообщений → проверить Session Index в RAM содержит ожидаемые сессии.

**Спеки:** `observer_specification_v1.3.md` секция 2

### Шаг 1.5: GLiNER

**Файлы:** `observer/ner.py`

- Загрузить GLiNER-small ONNX
- predict(text, labels) → entities[]
- Интегрировать в pipeline: если needs_ner → вызвать GLiNER

**Тест:** текст "решили использовать JWT для авторизации" → entity {type: "решение", value: "JWT для авторизации"}

**Спеки:** `observer_patch_v1.4.md` (TECH_LABELS_EXTENDED)

---

## Фаза 2: MCP Read Tools (агент может читать)

### Шаг 2.1: ctx.active(), ctx.get(), ctx.search()

**Файлы:** `tools/read.py`

- ctx.active() → top-N из RAM dict по Score
- ctx.get(session_id) → RAM dict lookup
- ctx.search(tags) → RAM dict filter

**Тест:** записать 5 сессий через Observer → ctx.active() возвращает top-5 по Score.

**Спеки:** `api_tools_specification.md`

### Шаг 2.2: ctx.semantic()

**Файлы:** `tools/read.py` (дополнить)

- query → embed → HNSWlib knn → top-20 → TinyBERT rerank → top-5
- Подгрузить TinyBERT ONNX (8MB)

**Тест:** записать 20 сессий → ctx.semantic("авторизация") → вернуть релевантные.

**Спеки:** `api_tools_specification.md`, `embedding_chain_v1.3.md` секция reranking

### Шаг 2.3: ctx.bridge()

**Файлы:** `tools/read.py` (дополнить)

- Собрать Session Bridge packet: active context + recent decisions + open conflicts

**Тест:** ctx.bridge() возвращает JSON с top-N active + anchors + urgents.

**Спеки:** `observer_specification_v1.3.md` секция Session Bridge

---

## Фаза 3: Dissolver + Tuner (система живёт)

### Шаг 3.1: Dissolver

**Файлы:** `dissolver/dissolver.py`

- recalc(session) → resolution
- apply_layer(session_id, resolution) → смена слоя
- batch_recalc() в Consolidation Worker (каждые 300s)
- decide_eviction() при RAM > soft_limit

**Тест:** создать 10 сессий, вызвать batch_recalc → resolution уменьшилось для старых.

**Спеки:** `dissolver_specification_v1.3.md`

### Шаг 3.2: Conflict Detector (Tuner, первый детектор)

**Файлы:** `tuner/conflict.py`

- Интегрировать inline в Observer шаг 5
- check_conflict() → cosine > 0.85 + разные anchor values → conflict_flag

**Тест:** сохранить "выбрали JWT" и "выбрали session tokens" → conflict_flag на обоих.

**Спеки:** `tuner_specification.md` секция Conflict Detector

### Шаг 3.3: Conductor bootstrap + event loop

**Файлы:** `core.py`

- Bootstrap 10 шагов (из conductor_specification.md)
- Event loop: Observer coroutine + Consolidation Worker
- Graceful shutdown: ctx.sync() + TRUNCATE checkpoint

**Тест:** запустить систему, подать 20 сообщений, graceful shutdown, рестарт → данные на месте.

**Спеки:** `conductor_specification.md`

---

## Фаза 4: Content Branch (полная двухпоточная архитектура)

### Шаг 4.1: content.save(), content.tag()

**Файлы:** `content/branch.py`, `tools/write.py`

- content_blocks + content_versions таблицы
- lz4 compression
- BGE-M3 lazy load при первом content.save()
- Content HNSWlib (persistent)

**Тест:** content.save(code_block) → версия 1 в SQLite + embedding в Content HNSWlib.

**Спеки:** `architecture_overview.md` секция 4

### Шаг 4.2: Tag verification

- cosine(tag_vector, content_vector) > 0.65 → verified
- GLiNER suggests additional tags

**Тест:** сохранить блок с тегами → tags_verified = 1 для правильных, 0 для ложных.

**Спеки:** `architecture_overview.md` секция 4.3

---

## Фаза 5: Feedback + Onboarding (система учится)

### Шаг 5.1: Implicit feedback

**Файлы:** `feedback/implicit.py`

- USE/DEEP_USE/IGNORE/REVISIT сигналы
- implicit_score EMA
- Интегрировать в ctx.get(), ctx.semantic(), ctx.full()

**Спеки:** `feedback_loop_v1.5.md`

### Шаг 5.2: Onboarding Pipeline

- Шаг 0 в Conductor bootstrap
- Если sessions_count == 0 AND history_source available → run onboarding
- Прогнать 10-50 сессий через Observer с ner_call_rate=1.0
- Построить профиль → записать config.json

**Спеки:** `onboarding_pipeline_specification.md` (нужно создать)

---

## Фаза 6: Tuner детекторы 2-4 + Admin tools

### Шаг 6.1: Остальные детекторы Tuner

- Semantic Drift Detector
- Anchor Validator
- Embedding Recalibrator (blue-green swap)

### Шаг 6.2: Admin tools

- ctx.status(), ctx.growth(), ctx.pulse()
- ctx.configure()
- ctx.sync(), ctx.load()

---

## Что можно пропустить на первой итерации

| Компонент | Почему можно отложить |
|-----------|----------------------|
| Tuner детекторы 2-4 | Conflict Detector достаточен на старте |
| Content tag verification | cosine check — nice-to-have |
| ctx.growth(), ctx.pulse() | Мониторинг, не core функционал |
| Urgency policy (v1.3) | Работает без неё, deadline management — улучшение |
| Experience Layer | v1.5, нужны данные |

## Что НЕЛЬЗЯ пропускать

| Компонент | Почему обязателен |
|-----------|-------------------|
| Observer pipeline (фильтр + embed + Score) | Без него нет записи |
| Session Index (RAM dict + HNSWlib) | Без него нет чтения |
| async flush (5s) | Без него потеря данных |
| Dissolver (хотя бы recalc + eviction) | Без него RAM переполнение |
| Conflict Detector | Без него накопление противоречий |
| ctx.active() + ctx.semantic() | Минимальный API для агента |

---

*Mnemostroma | Implementation Guide | 2026-03-25*
