# Mnemostroma — Мастер-индекс документации
## v1.7.1 — обновлено 2026-04-07

> μνήμη (mnḗmē, память) + στρῶμα (strôma, слой)
> The memory layer for AI agents
> Autonomous sidecar · ONNX INT8 · ~631MB RAM · ~20ms · offline · no GPU

---

## Архитектура — итоговая схема (4 слоя)

```
АГЕНТ
  └── видит: ctx.active() + intuition_signal (Stage Experience)

MNEMOSTROMA
  ├── СЛОЙ ПАМЯТИ (сознание)                    ← ✅ реализован v1.7.1
  │     Session Index, Anchor Layer, Precision Log
  │     Observer, Dissolver, Tuner, Conductor, HybridNER
  │
  ├── СЛОЙ ПЕРСИСТЕНТНОСТИ (Persistence)        ← ✅ реализован v1.7.1 (Phase 9.2)
  │     PersistenceLayer interface, atomic updates
  │     SQLite WAL path separation (WAL ⊆ DISK)
  │
  ├── СЛОЙ ОПЫТА                                ← ✅ реализован v1.7.1
  │     Experience Index / ExperienceCluster
  │     Intuition Signal (DO_THIS / AVOID_THIS / TENSION)
  │
  ├── СЛОЙ ПОДСОЗНАНИЯ (Stage C/D)              ← ✅ реализован v1.7.1
  │     Decay Engine (Stage C), Dreamer (Stage D)
  │     Pattern Encoder / Anomaly Detection
  │
  └── CONFIGURATION TUNER                       ← ✅ реализован (80+ параметров)
        🤖 самоконтроль / 🧠 самообучение / 🔒 защищённые
```

---

## Файлы документации

### Архитектура и стек

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `architecture_overview.md` | Полная архитектура: два потока, три слоя, SQLite схема, PersistenceLayer | v1.7.1 | ✅ обновлен |
| `stack_specification.md` | ONNX INT8 стек (E5-small), RAM, latency, PersistenceLayer v1.7.1 | v1.7.1 | ✅ обновлен |
| `ADR_002_replace_hnsw.md` | Архитектурное решение: замена HNSWlib на numpy MatrixSearch | v1.0 | ✅ |
| `ADR_001_script_vs_model.md` | Архитектурное решение: скрипт vs модель по слоям | v1.0 | ✅ |

### Планирование и Статус (MASTER)

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `docs/CHECKLIST_v2.md` | Детальный чек-лист фаз (1-9.2) | v2.1 | ✅ v1.7.1 |
| `docs/ROADMAP_v2.md` | Роадмап реализации (Фаза 9.2 DONE) | v2.1 | ✅ v1.7.1 |
| `docs/MASTER_ROADMAP.md` | Глобальный план работ и инварианты | v1.1 | ✅ v1.7.1 |
| `CHANGELOG.md` | История версий (v1.7.1: CLI + Split) | v1.7.1 | ✅ v1.7.1 |
| `MNESTROMA_WEAK_POINTS_v3.md` | Анализ 34 пунктов + аудит 9.2 | v3.3 | ✅ v1.7.1 |
| `MNEMOSTROMA_TODO_v3.md` | Текущий список задач (v3.2) | v3.2 | ✅ v1.7.1 |

### API и конфигурация

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `api_tools_specification.md` | Базовый API v1.0: ctx.*/content.* | v1.0 | ✅ |
| `api_tools_urgency_policy_v1.3.md` | Urgency policy: 3 уровня, 18 инструментов | v1.3 | ✅ |
| `ctx_sync_load_specification.md` | ctx.sync() и ctx.load() — полная спека | v1.4 | ✅ |
| `mnestroma_config_tuner_v1.0.md` | 80 параметров, 10 категорий, 🤖/🧠/🔒 | v1.0 | ✅ |

### Анализ и тесты

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `benchmark_plan.md` | План сравнения precision@5 vs MemGPT/Zep/Mem0 | v1.0 | ✨ новый |
| `tests/` | Набор из 303 интеграционных и юнит тестов | v1.7.1 | ✅ 303/303 |

---

## Стек (631MB RSS, CPU only)

| Роль | Модель | dim | RAM |
|------|--------|-----|-----|
| session_embedder | multilingual-e5-small int8 | 384 | ~420MB |
| content_embedder | multilingual-e5-small int8 | 384 | (shared) |
| NER | HybridNER (DistilBERT + regex) | — | ~170MB |
| Reranker | TinyBERT-L2-v2 | — | 8MB (lazy) |
| **TOTAL RSS** | | | **631MB** |

---

## Roadmap (Реальный статус v1.7.1)

| Версия | Что | Статус |
|--------|-----|--------|
| v1.7.0 | Core: Observer, MatrixSearch, Dreamer, Experience | ✅ DONE |
| Phase 9.2 | PersistenceLayer / WorkingMemory formal split | ✅ DONE |
| CLI Mode | `mnemostroma setup / on / off / status` | ✅ DONE |
| v1.7.1 | Packaging (pyproject.toml fixes + package data) | ✅ DONE |

---

## Недостающие документы

- `subconscious_layer_specification.md` (Stage C/D details)
- `monetization_strategy.md` (Open-core strategy)
- `deployment_guide.md` (CLI usage instructions)

---

*Mnemostroma | INDEX v1.7.1 | 2026-04-07*
*Документов: 33 | Тестов: 303/303 | RAM: 631MB | Статус: Stable v1.7.1*
