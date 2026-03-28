# Mnemostroma — Data Flow Specification
> Сквозной путь данных: от I/O агента до хранилища и обратно
> 2026-03-25

---

## 1. Write Path: агент говорит → система запоминает

```
Agent I/O (output текст)
│
▼ async, не блокирует агента
┌─────────────────────────────────────────────────────────────┐
│ OBSERVER PIPELINE                                           │
│                                                             │
│ [1] Chunking (~0.2ms)                                       │
│     output > 256 tokens → split с overlap 32                │
│     output ≤ 256 tokens → 1 chunk                           │
│                                                             │
│ [2] Детерминированный фильтр (~0.1ms per chunk)             │
│     ├── importance: background → ОТБРОСИТЬ                  │
│     ├── importance: principle → прямо в Session Index        │
│     ├── precision найден → Precision Log + Anchor Layer      │
│     ├── importance: critical + entities ясны → Session Index │
│     └── importance: important / unclear → [3] GLiNER         │
│                                                             │
│     ~70% chunks обработаны БЕЗ GLiNER                       │
│                                                             │
│ [3] GLiNER NER (~8ms, ~30% chunks)                          │
│     zero-shot entity extraction                             │
│     → entities[] с type + value + score                     │
│                                                             │
│ [4] Компрессия → brief(50 chars) + tags[]  (~0.3ms)         │
│                                                             │
│ [5] EmbeddingGemma → float16[512]  (~12ms)                  │
│     векторизирует brief+tags, НЕ raw chunk                  │
│                                                             │
│ [6] TinyBERT rerank → проверка релевантности  (~6ms)        │
│                                                             │
│ [7] Score = α×R + β×T + γ×I  (~0.01ms)                      │
│     Write Profile: 0.5/0.3/0.2                              │
│                                                             │
│ [8] Tuner inline check  (~1ms)                              │
│     Conflict Detector: cosine > 0.85 + разные decisions?    │
│     → conflict_flag = True → Dissolver заморозит            │
│                                                             │
│ [9] Сохранение (~1ms RAM, async SQLite)                     │
│     ├── RAM: Session Index dict update                      │
│     ├── RAM: HNSWlib Session add_item                       │
│     ├── RAM: urgency_index (если urgency ≠ none)            │
│     └── async → pending_updates queue                       │
│                                                             │
│ [10] Implicit Feedback capture                              │
│      (USE/IGNORE сигналы записываются при чтении, не здесь) │
└─────────────────────────────────────────────────────────────┘
│
▼ каждые 5 секунд (async_flush_interval)
┌─────────────────────────────────────────────────────────────┐
│ ASYNC FLUSH QUEUE → SQLite WAL                              │
│                                                             │
│ pending_updates queue → batch до 50 записей → SQLite        │
│                                                             │
│ sessions INSERT/UPDATE                                      │
│ anchors INSERT (если anchor_flag)                           │
│ precision_log INSERT (если precision_flag)                  │
│                                                             │
│ Потеря при краше: ≤5 секунд рабочих данных                  │
└─────────────────────────────────────────────────────────────┘
│
▼ конец сессии (опционально)
┌─────────────────────────────────────────────────────────────┐
│ CONTENT_FULL FLUSH (Вариант B)                              │
│                                                             │
│ Text accumulator → SQLite sessions.content_full             │
│ Один атомарный INSERT                                       │
│ Это подстраховка, не рабочие данные                         │
└─────────────────────────────────────────────────────────────┘
```

### Latency write path (суммарно)

| Шаг | Время | Условие |
|-----|-------|---------|
| Без NER (70% случаев) | ~14ms | filter + embed + score + save |
| С NER (30% случаев) | ~22ms | + GLiNER 8ms |
| Async flush | не блокирует | каждые 5s в фоне |

---

## 2. Read Path: агент спрашивает → система отвечает

```
Agent tool call
│
├── ctx.active()  ──────────► RAM dict top-N по Score
│                              Latency: <0.01ms
│                              Данные: brief + tags + importance + anchors
│                              Feedback: нет (пассивный read)
│
├── ctx.get(id)  ───────────► RAM dict lookup по session_id
│                              Latency: <0.01ms
│                              Feedback: USE signal → use_count++
│
├── ctx.search(tags)  ──────► RAM dict filter по тегам
│                              Latency: <0.1ms
│                              Feedback: нет (bulk read)
│
├── ctx.semantic(query)  ───► [1] EmbeddingGemma(query) → vec512  ~12ms
│                             [2] HNSWlib knn(vec, top-20)         ~2ms
│                             [3] TinyBERT rerank(query, top-20)   ~6ms
│                             [4] Return top-5 briefs              <0.1ms
│                             Latency total: ~20ms
│                             Score Profile: Search (0.6/0.3/0.1)
│                             Feedback: USE для top-5
│                                       IGNORE если re-query <5s
│
├── ctx.full(id)  ──────────► SQLite SELECT by PK
│                              Latency: <0.5ms
│                              Feedback: DEEP_USE signal
│
├── ctx.anchors(filter)  ───► RAM dict → anchors[]
│                              Latency: <0.1ms
│
├── ctx.precision(filter)  ─► RAM dict (Hot) или SQLite (Warm+)
│                              Latency: <0.1ms (RAM) / <1ms (SQLite)
│
├── ctx.bridge()  ──────────► Сборка Session Bridge packet
│                              active_context + decisions + conflicts + urgents
│                              Latency: <0.01ms
│
├── ctx.urgent()  ──────────► urgency_index filter (active only)
│                              Latency: <0.01ms
│
└── ctx.expire()  ──────────► urgency_index filter (expired)
                               Latency: <0.01ms
```

### Где данные живут при чтении

```
            RAM dict              HNSWlib Session        SQLite WAL
            ────────              ──────────────         ──────────
ctx.active  ✦ (primary)
ctx.get     ✦ (primary)
ctx.search  ✦ (primary)
ctx.semantic                      ✦ (knn search)         fallback
ctx.full                                                  ✦ (primary)
ctx.anchors ✦ (Hot/Warm)                                  fallback
ctx.bridge  ✦ (primary)
```

**Принцип:** 95% чтений — только RAM. SQLite = cold storage для ctx.full() и архивных сессий.

---

## 3. Content Write Path: агент сохраняет артефакт

```
Agent: content.save(block)
│
▼
┌─────────────────────────────────────────────────────────────┐
│ CONTENT BRANCH                                              │
│                                                             │
│ [1] Создать/обновить content_block                          │
│     content_id, content_type, parent_id, project_id         │
│                                                             │
│ [2] Создать content_version                                 │
│     lz4 compress → content_raw                              │
│     content_diff (если version > 1)                         │
│     why_changed (если указано агентом)                       │
│                                                             │
│ [3] BGE-M3 embed (lazy load — загружается при первом вызове)│
│     content_raw → float16[512] → Content HNSWlib            │
│     Latency: ~50ms (первый раз +2-3s на загрузку модели)    │
│                                                             │
│ [4] Tag verification (опционально)                          │
│     cosine(tag_vec, content_vec) > 0.65 → verified          │
│     GLiNER suggests additional tags                         │
│                                                             │
│ [5] SQLite INSERT                                           │
│     content_blocks + content_versions                       │
│     Content HNSWlib persistent save                         │
└─────────────────────────────────────────────────────────────┘
```

---

## 4. Background Processes (фоновые задачи)

```
┌─────────────────────────────────────────────────────────────┐
│ CONSOLIDATION WORKER (каждые 300s)                          │
│                                                             │
│ [1] Dissolver.batch_recalc()                                │
│     Для каждой сессии в RAM:                                │
│       resolution = time_factor × use_factor × prog_factor   │
│       apply_layer(session_id, resolution)                   │
│     Latency: ~1ms для 500 сессий                            │
│                                                             │
│ [2] Dissolver.urgency_check()                               │
│     Найти deadline_ts < now AND urgency_active = True       │
│     → пометить expired                                     │
│     → compress_to_bare_entity()                             │
│                                                             │
│ [3] Implicit Feedback: REVISIT detection                    │
│     Подсчёт: session_id встречался 3+ раз в use_history     │
│     → REVISIT signal → implicit_score boost                 │
│                                                             │
│ [4] RAM eviction check                                      │
│     if RAM > soft_limit (380MB):                            │
│       sorted by Score → evict lowest → apply_layer()        │
│     if RAM > hard_limit (480MB):                            │
│       aggressive evict immediately                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ TUNER BACKGROUND (нечастые задачи)                          │
│                                                             │
│ Каждые 50 сессий:                                           │
│   Anchor Validator → check TTL → пометить stale             │
│                                                             │
│ Каждые 24 часа:                                             │
│   Semantic Drift Detector → centroid comparison              │
│                                                             │
│ При смене модели:                                           │
│   Embedding Recalibrator → blue-green HNSWlib swap          │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Bootstrap Path (холодный старт)

```
Conductor.bootstrap()
│
├── [0] Onboarding (если sessions_count == 0 AND history available)
│       Прогнать 10-50 сессий истории → config.json
│
├── [1] Загрузить config.json
├── [2] Открыть SQLite WAL connection
├── [3] Загрузить EmbeddingGemma ONNX (52MB)
├── [4] Загрузить GLiNER-small ONNX (42MB)
├── [5] Загрузить TinyBERT ONNX (8MB)
├── [6] НЕ загружать BGE-M3 (lazy load при content.save())
├── [7] Восстановить HNSWlib Session из SQLite embeddings
├── [8] Загрузить последние N сессий в RAM по Score (warm cache)
├── [9] Восстановить urgency_index из SQLite WHERE urgency_active=1
├── [10] Запустить Observer async coroutine
├── [11] Запустить Consolidation Worker (каждые 300s)
└── [12] Готов к работе
```

---

## 6. Graceful Shutdown Path

```
SIGTERM / ctx.sync() при shutdown
│
├── [1] Остановить Observer (дождаться завершения текущей обработки)
├── [2] Drain pending_updates queue → SQLite
├── [3] Flush content_full accumulator → SQLite
├── [4] WAL checkpoint TRUNCATE (полный)
├── [5] Сохранить Content HNSWlib на диск
├── [6] Закрыть SQLite connection
└── [7] Exit
```

---

## 7. Timing Diagram: одно сообщение агента

```
t=0ms     Agent output received
t=0.1ms   [filter] importance=important, needs_ner=true
t=0.2ms   [chunking] 1 chunk (< 256 tokens)
t=8ms     [GLiNER] entities: [{type:"решение", value:"JWT auth"}]
t=8.3ms   [compress] brief="Выбрали JWT auth" tags=["#JWT","#auth"]
t=20ms    [embed] EmbeddingGemma → vec512
t=26ms    [rerank] TinyBERT → relevance confirmed
t=26.01ms [Score] 0.5×0.89 + 0.3×1.0 + 0.2×0.5 = 0.845
t=27ms    [Tuner] no conflict detected
t=27.5ms  [save] RAM dict updated, HNSWlib add_item
t=27.5ms  → async task: pending_updates.put(entity)
           ↓
t=5000ms  [flush] batch write → SQLite WAL (background, every 5s)
```

**Общее время блокировки агента: 0ms** (весь pipeline async).
Общее время обработки: ~27ms.

---

*Mnemostroma | Data Flow Specification | 2026-03-25*
