# Цепочка эмбеддинга — полная схема v1.3
## RAM-First Context System (все элементы без пропусков)

---

## ВЕТКА 1: Сессионный контекст (Observer)

```
raw text (agent output)
    │
    ▼
[1] CHUNKING — сессионный                                RAM: 0MB
    │  Функция: разбить длинный output на смысловые фрагменты
    │  Кто: Observer шаг 0 (до всего)
    │  Метод: sentence boundary detection (regex, не ML)
    │         абзацы / точки / переносы строк
    │  Параметр: max_chunk_tokens = 512 (оптимум для E5-small)
    │  Если output < 512 токенов → чанкинг не нужен (1 чанк)
    │  Если output > 512 → split с overlap 32 токена
    │  Latency: ~0.2ms
    │
    ▼
[2] ДЕТЕРМИНИРОВАННЫЙ ФИЛЬТР (на каждом чанке)          RAM: 0MB
    │  Функция: regex + signals → importance, conflict, precision
    │  Кто: Observer шаг 1
    │  Latency: ~0.1ms per chunk
    │  60% чанков → путь без NER
    │  Чанки importance=background без сигналов → ОТБРОСИТЬ (не векторизировать)
    │
    ├── precision → [3] Precision Log сразу
    └── needs_ner → [4] HybridNER
    │
    ▼ (только чанки важнее background)
[3] PRECISION LOG — прямая запись                        RAM: ~3MB (данные)
    │  Функция: URL/phone/email/number → anchors без эмбеддинга
    │  Кто: Observer шаг 1б (параллельно с основным путём)
    │  Latency: <0.01ms (RAM dict + async SQLite)
    │
    ▼
[4] HybridNER (DistilBERT int8 + Regex)                 RAM: ~178MB (dedicated)
    │  Функция: chunk → entities[] extracted
    │  Кто: Observer шаг 2
    │  Latency: ~10ms per chunk
    │  Выход: [{type, value, score}] score > 0.7
    │
    ▼
[5] NER ВЕРИФИКАЦИЯ — двухступенчатая                    RAM: 0MB доп.
    │  Функция: score 0.70–0.85 → cosine к entity centroid
    │  Кто: Observer шаг 2б
    │  Latency: +2ms (переиспользует [7] E5-small)
    │
    ▼
[6] КОМПРЕССИЯ ЧАНКА → BRIEF + TAGS                      RAM: 0MB
    │  Функция: chunk (512 токенов) → brief (50 символов) + tags[]
    │  Кто: Observer шаг 2в (детерминированная, не ML)
    │  Метод:
    │    brief = первое предложение чанка[:50]
    │           + ключевые сигнальные слова
    │    tags  = entities из [4] + keyword extraction (TF-IDF style)
    │  Latency: ~0.3ms
    │  ВАЖНО: векторизируем brief+tags, НЕ raw chunk
    │         (экономия: 512 токенов → ~15 токенов)
    │
    ▼
[7] TOKENIZER — HuggingFace (shared)                     RAM: 270MB (dedicated)
    │  Функция: brief+tags → input_ids
    │  Кто: Observer шаг 3
    │  Latency: ~0.2ms (короткий текст после компрессии)
    │
    ▼
[8] multilingual-e5-small ONNX INT8                      RAM: 138MB (dedicated)
    │  Функция: input_ids → вектор 384d float16
    │  Кто: Observer шаг 3
    │  Latency: ~15ms
    │  Вход:  brief+tags (~15 токенов) — НЕ raw 512 токенов
    │  Выход: float16[384] — вектор сессии
    │  Переиспользуется во всех ветках — 0MB доп.
    │
    ▼
[10] HNSWlib Session Index (dim=384)                     RAM: ~10MB (данные)
    │  Функция: add_item(vector, session_id)
    │  Кто: Observer шаг 5
    │  Latency: ~0.5ms
    │  Хранит ВСЕ векторы вечно
    │
    ▼
[11] RAM Session Index (dict)                            RAM: ~185MB (данные)
    │  Функция: session_id → {brief, tags, anchors, score, layer}
    │  Кто: Observer (запись) / Agent (чтение)
    │  Latency: <0.01ms
    │
    ▼
[12] SQLite WAL — sessions                               RAM: 0MB (диск)
       Функция: async flush
       Latency: <5ms async
```
```

---

## ВЕТКА 2: Контентный эмбеддинг (Agent Content)

```
raw content (код / текст / сцена)
    │
    ▼
[13] CHUNKING — контентный                               RAM: 0MB
    │  Функция: разбить большой контентный блок на части
    │  Кто: Agent Content при content.save()
    │  Стратегия зависит от content_type:
    │    code     → по функциям/классам (AST-aware split)
    │    text     → по абзацам (max 512 токенов)
    │    chapter  → по разделам
    │  max_chunk_tokens = 512 (E5-small оптимум)
    │  overlap = 64 токена (для связности)
    │  Latency: ~0.5ms
    │
    ▼
[14] LZ4 COMPRESS (raw content)                          RAM: 0MB
    │  Функция: content_raw → BLOB lossless
    │  Кто: Agent Content (параллельно с эмбеддингом)
    │  Latency: <1ms
    │
    ▼
[15] TOKENIZER — HuggingFace (shared)                    RAM: 270MB (shared)
    │  Функция: chunk → input_ids
    │  Latency: ~0.5ms per chunk
    │
    ▼
[16] multilingual-e5-small ONNX INT8                     RAM: 138MB (shared)
    │  Функция: input_ids → вектор 384d float16 per chunk
    │  Кто: Agent Content
    │  Latency: ~15ms per chunk
    │  Multi-chunk: векторизируем каждый чанк отдельно
    │
    ▼
[17] CHUNK POOLING — агрегация чанков                    RAM: 0MB
    │  Функция: [vec_chunk1, vec_chunk2, ...] → один вектор блока
    │  Кто: Agent Content
    │  Метод: weighted mean (вес = позиция, первый чанк важнее)
    │         vec_block = mean([v1*1.0, v2*0.8, v3*0.6, ...])
    │  Latency: <0.5ms (numpy операция)
    │  Выход: float16[384] — финальный вектор контентного блока
    │
    ▼
[17а] ВЕРИФИКАЦИЯ ТЕГОВ                                  RAM: 0MB доп.
    │  Функция: cosine(embed(tag), vec_block) > 0.65 ?
    │  Кто: Agent Content
    │  Переиспользует [8] E5-small для тегов
    │  Latency: +1ms per tag
    │
    ▼
[18] ВЕРСИОННЫЙ DIFF                                     RAM: 0MB
    │  Функция: content_hash сравнение + text diff
    │  Кто: Agent Content при новой версии
    │  Метод: SHA256(content_raw) → если hash совпадает → дубль (skip)
    │         если нет → unified diff → content_diff поле
    │  Latency: <1ms
    │
    ▼
[19] HNSWlib Content Index (dim=384)                     RAM: ~2MB (данные)
    │  Функция: add_item(vec_block, content_id+version)
    │  Персистентный → content_hnsw.bin
    │  Latency: ~0.5ms
    │
    ▼
[20] RAM Content Index (dict)                            RAM: ~5MB (данные)
    │  Latency: <0.01ms
    │
    ▼
[21] SQLite WAL — content_versions                       RAM: 0MB (диск)
       lz4 BLOB + embedding BLOB + diff text
       async flush
```

---

## ВЕТКА 3: Поиск ctx.semantic() (Agent читает)

```
query string
    │
    ▼
[22] QUERY EXPANSION (опционально)                       RAM: 0MB
    │  Функция: query → query + синонимы/теги
    │  Кто: ctx.semantic() если expand=True
    │  Метод: детерминированный lookup по тегам из RAM Index
    │  Пример: "авторизация" → "авторизация #JWT #auth #токен"
    │  Latency: <0.1ms
    │
    ▼
[23] TOKENIZER (shared)                                  RAM: 270MB (shared)
    │  Latency: ~0.5ms
    │
    ▼
[24] multilingual-e5-small ONNX INT8                     RAM: 138MB (shared)
    │  Функция: query → вектор 384d
    │  Latency: ~15ms
    │
    ▼
[25] HNSWlib Session Index — knn_query                   RAM: ~10MB (shared)
    │  Функция: вектор → top-20 candidates + distances
    │  Latency: ~1.5ms
    │  Ищет по ВСЕМ слоям (все векторы вечно)
    │
    ▼
[26] ПРЕДФИЛЬТР кандидатов                               RAM: 0MB
    │  Функция: отфильтровать нерелевантные по тегам/типу
    │  Кто: ctx.semantic() перед реранкингом
    │  Метод: tag intersection с RAM Index
    │  Latency: <0.1ms
    │  Цель: передать TinyBERT только сильных кандидатов
    │
    ▼
[27] TinyBERT-L2-v2 ONNX INT8                           RAM: 8MB (dedicated)
    │  Функция: cross-encoder реранкинг top-20 → top-5
    │  Кто: ctx.semantic()
    │  Latency: ~6ms per пара
    │  Вход: [CLS] query [SEP] brief [SEP]
    │  Выход: relevance score
    │
    ▼
[28] SCORE ФИНАЛЬНЫЙ                                     RAM: 0MB
    │  Функция: rerank_score * 0.6 + temporal_score * 0.3 + importance * 0.1
    │  Кто: ctx.semantic()
    │  Latency: <0.1ms
    │  Примечание: веса отличаются от Score Observer
    │              (поиск важнее свежесть менее критична)
    │
    ▼
[29] RAM dict lookup + lazy load                         RAM: shared
       Функция: session_id → brief + tags + anchors
       Miss в RAM → SQLite lazy load → вернуть в RAM
       Latency: <0.01ms (hit) / <0.5ms (miss→SQLite)
```

---

## Сводная таблица — все элементы

```
#     Элемент                      Ветка   Кто           RAM        Latency
───────────────────────────────────────────────────────────────────────────────
[1]   Chunking сессионный          1       Observer       0MB        ~0.2ms
[2]   Детерм. фильтр               1,3     Observer       0MB        ~0.1ms
[3]   Precision Log запись         1       Observer       3MB RAM    <0.01ms
[4]   HybridNER (DistilBERT)       1       Observer     178MB        ~10ms
[5]   NER верификация              1       Observer       0MB доп.   ~2ms
[6]   Компрессия → brief+tags      1       Observer       0MB        ~0.3ms
[7]   Tokenizer (HF) - Shared      1,2,3   Observer/Agent 270MB      ~0.2ms
[8]   multilingual-e5-small        1,2,3   Observer/Agent 138MB      ~15ms
[10]  HNSWlib Session Index        1,3     Observer       10MB       ~0.5ms
[11]  RAM Session Index dict       1,3     Observer/Agent 185MB      <0.01ms
[12]  SQLite sessions flush        1       Observer       0MB диск   <5ms async
───────────────────────────────────────────────────────────────────────────────
[13]  Chunking контентный          2       Agent           0MB        ~0.5ms
[14]  LZ4 compress                 2       Agent           0MB        <1ms
[16]  multilingual-e5-small (sh)   2       Agent           0MB доп.   ~15ms
[17]  Chunk pooling (weighted)     2       Agent           0MB        <0.5ms
[17а] Верификация тегов            2       Agent           0MB доп.   ~1ms/tag
[18]  Версионный diff (hash+text)  2       Agent           0MB        <1ms
[19]  HNSWlib Content Index        2       Agent            2MB       ~0.5ms
[20]  RAM Content Index dict       2       Agent            5MB       <0.01ms
[21]  SQLite content_versions      2       Agent           0MB диск   <5ms async
───────────────────────────────────────────────────────────────────────────────
[22]  Query expansion (опц.)       3       Agent           0MB        <0.1ms
[23]  Tokenizer (shared)           3       Agent           0MB доп.   ~0.5ms
[24]  e5-small (shared)            3       Agent           0MB доп.   ~15ms
[25]  HNSWlib knn_query (shared)   3       Agent          10MB shared ~1.5ms
[26]  Предфильтр кандидатов        3       Agent           0MB        <0.1ms
[27]  TinyBERT reranker INT8       3       Agent           8MB        ~6ms
[28]  Score финальный              3       Agent           0MB        <0.1ms
[29]  RAM lookup + lazy load       3       Agent           0MB доп.   <0.01ms
───────────────────────────────────────────────────────────────────────────────
RUNTIME (фиксированный):
      ONNX Runtime 1.18+           все     —              45MB       —
      Python 3.11 slim             все     —              35MB       —
───────────────────────────────────────────────────────────────────────────────

ИТОГО МОДЕЛИ + RUNTIME:                                  345MB
ИТОГО ДАННЫЕ:                                            205MB
ИТОГО СИСТЕМА v1.2:                                      550MB
БУФЕР:                                                    50MB
```

---

## Latency полных цепочек

```
ВЕТКА 1 — Observer write (async, агент не блокируется):
  [1]  Chunking:           0.2ms
  [2]  Детерм. фильтр:     0.1ms
  [4]  GLiNER-medium:     18.0ms  (только ~30% случаев)
  [5]  NER верификация:    2.0ms
  [6]  Компрессия:         0.3ms
  [7]  Tokenizer:          0.2ms
  [8]  EmbeddingGemma:    12.0ms
  [10] HNSWlib add:        0.5ms
  ──────────────────────────────
  ИТОГО (с NER):          ~33ms   async
  ИТОГО (без NER, 70%):   ~13ms   async

ВЕТКА 2 — content.save():
  [13] Chunking:           0.5ms
  [14] LZ4:                1.0ms
  [15] Tokenizer:          0.5ms
  [16] BGE-M3 × N чанков: 12ms × N
  [17] Chunk pooling:      0.5ms
  [17а]Верификация тегов:  1ms × T (T = кол-во тегов)
  [18] Hash + diff:        1.0ms
  [19] HNSWlib add:        0.5ms
  ──────────────────────────────
  ИТОГО (1 чанк, 3 тега): ~20ms

ВЕТКА 3 — ctx.semantic():
  [22] Query expansion:    0.1ms
  [23] Tokenizer:          0.5ms
  [24] EmbeddingGemma:    12.0ms
  [25] HNSWlib knn:        1.5ms
  [26] Предфильтр:         0.1ms
  [27] TinyBERT rerank:    6.0ms
  [28] Score:              0.1ms
  [29] RAM lookup:         0.01ms
  ──────────────────────────────
  ИТОГО:                  ~20ms   ← без изменений vs v1.0
```

---

## Что добавлено в v1.3 vs предыдущей схемы

| Пропущенный элемент | Где в цепочке | Почему важен |
|---|---|---|
| Chunking сессионный [1] | До фильтра | Длинные outputs без чанкинга дают один усреднённый вектор — теряем детали |
| Chunking контентный [13] | До BGE-M3 | Код > 512 токенов не влезает в модель без разбивки |
| Компрессия → brief+tags [6] | После NER, до векторизации | Векторизируем сжатое (15 токенов), не raw (256) — в 17× быстрее |
| Chunk pooling [17] | После BGE-M3 | Агрегация нескольких чанков в один вектор блока |
| Предфильтр кандидатов [26] | Перед реранкингом | TinyBERT видит только сильных кандидатов — экономия 6ms |
| Query expansion [22] | До векторизации запроса | Улучшает recall без изменения latency модели |
| Версионный diff [18] | При content.save() | Заменяет ColBERT для различения версий |
| PCA 512→256 [9] | Фоново при давлении RAM | Экстренная экономия RAM без перезагрузки |
