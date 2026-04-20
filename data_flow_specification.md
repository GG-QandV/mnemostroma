# Mnemostroma — Data Flow Specification
## Сквозной путь данных: от I/O агента до хранилища и обратно
## v1.7.1 | 2026-04-07 | Phase 9.2 Complete

---

## 1. Write Path: агент говорит → система запоминает

```
Agent I/O (output текст)
│
▼ async, не блокирует работу агента
┌─────────────────────────────────────────────────────────────┐
│ OBSERVER PIPELINE                                           │
│                                                             │
│ [1] Chunking (~0.2ms)                                       │
│ [2] Детерминированный фильтр (~0.1ms per chunk)             │
│ [3] GLiNER NER (~8ms, ~30% chunks)                          │
│ [4] Компрессия → brief(50 chars) + tags[]  (~0.3ms)         │
│ [5] multilingual-e5-small → float16[384]  (~10ms)           │
│ [6] TinyBERT rerank → проверка релевантности  (~6ms)        │
│ [7] Score Write Profile (α=0.5, β=0.3, γ=0.2)               │
│ [8] Tuner inline check (Conflict Detector)  (~1ms)          │
│                                                             │
│ [9] Сохранение через PersistenceLayer (Phase 9.2)           │
│     ├── RAM: Session Index dict update                      │
│     ├── RAM: MatrixSearch Session add_item                  │
│     ├── AWAIT: ctx.persistence.save_anchor() (if anchor)    │
│     └── ENQUEUE: persistence.enqueue_session() (batch 5s)   │
└─────────────────────────────────────────────────────────────┘
│
▼ каждые 5 секунд (enqueue_session loop)
┌─────────────────────────────────────────────────────────────┐
│ PERSISTENCE LAYER → SQLite WAL                              │
│                                                             │
│ Очередь сессий → batch до 50 записей → SQLite               │
│ Потеря при краше: ≤5 секунд только для текстовых сессий     │
│ Якоря и Опыт: потеря 0 (атомарный await)                    │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. Read Path: агент спрашивает → система отвечает

```
Agent tool call
│
├── ctx.active()  ──────────► RAM dict top-N по Score (<0.01ms)
│
├── ctx.semantic(query)  ───► [1] e5-small(query) → vec384  ~10ms
│                             [2] MatrixSearch ANN(vec, 20)  ~0.5ms
│                             [3] TinyBERT rerank(query, 20) ~6ms
│                             Latency total: ~17-20ms
│                             Score Profile: Search (0.6/0.3/0.1)
│
├── ctx.full(id)  ──────────► PersistenceLayer → SQLite SELECT (<0.5ms)
│
└── ctx.bridge()  ──────────► Сборка Session Bridge packet (<0.01ms)
```

---

## 3. Background Processes (v1.7.1)

┌─────────────────────────────────────────────────────────────┐
│ CONSOLIDATION WORKER (каждые 300s)                          │
│                                                             │
│ [1] Dissolver.batch_recalc() (resolution decay)             │
│ [2] Dreamer.process() (Stage D: re-evaluation)              │
│ [3] DecayEngine (Stage C: background forgetting)            │
│ [4] RAM eviction check (Soft Limit 380MB / Hard 480MB)       │
└─────────────────────────────────────────────────────────────┘

---

## 4. Bootstrap Path (v1.7.1)

1. **mnemostroma setup**: Подготовка `~/.mnemostroma/`.
2. **PersistenceLayer init**: Открытие `mnemostroma.db` (WAL mode).
3. **MatrixSearch rebuild**: Восстановление индекса из SQLite embeddings.
4. **Hot Cache Load**: Загрузка `RAM_HOT` сессий.
5. **Start Workers**: Запуск Observer, Dreamer, Decay.

---

*Mnemostroma | Data Flow Specification | v1.7.1 | 2026-04-07*
*μνήμη + στρῶма · 303 tests · PersistenceLayer protocol*
