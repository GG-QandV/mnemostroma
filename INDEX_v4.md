# Mnemostroma — Мастер-индекс документации
## v1.4 — обновлено 2026-03-25

> μνήμη (mnḗmē, память) + στρῶμα (strôma, слой)
> The memory layer for AI agents
> Autonomous sidecar · ONNX INT8 · ~600MB RAM · ~20ms · offline · no GPU

---

## Архитектура — итоговая схема (4 слоя)

```
АГЕНТ
  └── видит: ctx.active() + intuition_signal (v1.5+)

MNEMOSTROMA
  ├── СЛОЙ ПАМЯТИ (сознание)                    ← спеки v1.3 + патчи v1.4
  │     Session Index, Anchor Layer, Precision Log
  │     Observer, Dissolver, Tuner, Conductor
  │
  ├── СЛОЙ ОПЫТА                                ← спека в SESSION_BRIDGE + ADR_001
  │     +Experience Index / -Experience Index
  │     ExperienceCluster (maturity: novice→master)
  │     Intuition Signal (DO_THIS / AVOID_THIS / TENSION)
  │
  ├── СЛОЙ ПОДСОЗНАНИЯ                          ← концепция, реализация v3.0
  │     Subconscious Evaluator (скрипт до v3.0)
  │     Pattern Encoder ~8MB ONNX (v3.0, 500+ записей)
  │     Anomaly Autoencoder ~3MB ONNX (v3.0, 500+ записей)
  │     Гипотеза: Hypómnema Strōma
  │
  └── CONFIGURATION TUNER                       ← спека готова, 80 параметров
        🤖 самоконтроль (10 params)
        🧠 самообучение (10 params, после 100+ сессий)
        🔒 защищённые (9 params)
```

---

## Файлы документации

### Архитектура и стек

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `architecture_overview.md` | Полная архитектура: два потока, три слоя, SQLite схема, Score | v1.0 | ✅ |
| `architecture_patch_v1.4.md` | embedding_model_version, dual Score profiles (Write/Search) | v1.4 | ✅ |
| `stack_specification.md` | ONNX INT8 стек, 342MB, latency, код инициализации | v1.0 | ✅ |
| `embedding_chain_v1.3.md` | Цепочка эмбеддинга: 3 ветки, чанкинг, компрессия, pooling | v1.3 | ✅ |
| `ADR_001_script_vs_model.md` | Архитектурное решение: скрипт vs модель по слоям | v1.0 | ✅ |

### Компоненты (спецификации)

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `observer_specification_v1.3.md` | Observer pipeline, urgency, detect_principle | v1.3 | ✅ |
| `observer_patch_v1.4.md` | GLiNER dual-mode, TECH_LABELS, process_vec per-message | v1.4 | ✅ |
| `dissolver_specification_v1.3.md` | Dissolver: resolution, 5 слоёв, urgency_check, compress | v1.3 | ✅ |
| `dissolver_patch_v1.4.md` | Content HOT INDEX eviction: LRU + active flag | v1.4 | ✅ |
| `tuner_specification.md` | Tuner: 4 детектора (Conflict, Drift, Anchor, Recalibrator) | v1.1 | ✅ |
| `tuner_specification_v1.4.md` | Blue-green HNSWlib swap, decisions_contradict() 5 шагов | v1.4 | ✅ |
| `conductor_specification.md` | Conductor: bootstrap 10 шагов, event loop, 4 deployment modes | v1.1 | ✅ |
| `feedback_loop_v1.5.md` | Implicit feedback: USE/DEEP_USE/IGNORE/REVISIT сигналы | v1.5 | ✅ |

### API и конфигурация

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `api_tools_specification.md` | Базовый API v1.0: ctx.*/content.*, паттерны агента | v1.0 | ✅ |
| `api_tools_specification_v2.md` | Дополнение: ctx.status(), ctx.growth(), ctx.pulse() | v1.1 | ✅ |
| `api_tools_urgency_policy_v1.3.md` | Urgency policy: 3 уровня, 18 инструментов | v1.3 | ✅ |
| `ctx_sync_load_specification.md` | ctx.sync() и ctx.load() — полная спека | v1.4 | ✅ |
| `mnestroma_config_tuner_v1.0.md` | 62 параметра, 10 категорий, 🤖/🧠/🔒 | v1.0 | ✅ |
| `config_tuner_patch_v1.4.md` | +18 параметров → 80 итого. Experience Layer, GLiNER dual | v1.4 | ✅ |

### Анализ и статус

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `MNESTROMA_WEAK_POINTS_v2.md` | 23 weak points: 16✅, 3⚠️, 3🔄, 0🔴 | v2.0 | ⚠️ нужен v3 |
| `MNESTROMA_WEAK_POINTS_v3.md` | Пересмотр: все 23 пункта → ✅ | v3.0 | ✅ новый |
| `MNEMOSTROMA_TODO_v1.md` | Остаток задач: P0/P1/P2 | v1.0 | ⚠️ нужен v2 |

### Описания продукта

| Файл | Содержание | Версия | Статус |
|------|-----------|--------|--------|
| `mnemostroma_description_technical.md` | Для разработчиков (содержит детали реализации) | v1.0 | ⚠️ нужна правка |
| `mnemostroma_description_marketing.md` | Для вайб-кодеров / пользователей | v1.0 | ✅ |

### Session Bridges

| Файл | Содержание | Дата |
|------|-----------|------|
| `SESSION_BRIDGE_2026_03_09.md` | Спринт документации: Experience Layer, ADR_001, naming | 2026-03-09 |

### Архивные версии

| Файл | Содержание | Статус |
|------|-----------|--------|
| `INDEX_v2.md` | Мастер-индекс v1.1 | 📦 архив |
| `INDEX_v3.md` | Мастер-индекс v1.3 | 📦 архив |
| `dissolver_specification.md` | Dissolver v1.1 (до urgency patch) | 📦 архив |
| `observer_specification.md` | Observer v1.0 (до urgency patch) | 📦 архив |
| `mnestroma_Config_tuner.md` | Дубль config_tuner (содержание идентично) | 📦 дубль |

---

## Стек (342MB INT8, CPU only)

| Компонент | RAM | Роль |
|-----------|-----|------|
| EmbeddingGemma-300m ONNX INT8 | 52MB | Эмбеддер сессий, 512d MRL |
| BGE-M3 ONNX INT8 | 145MB | Эмбеддер контента (lazy load) |
| GLiNER-small-v2.1 ONNX INT8 | 42MB | NER Observer zero-shot |
| TinyBERT-L-2-v2 ONNX INT8 | 8MB | Реранкер |
| ONNX Runtime + Python + tokenizers | 95MB | Runtime |
| **Итого модели** | **342MB** | |
| + Session Index RAM (200 сессий) | ~200MB | |
| + urgency_index RAM | ~1MB | |
| **Итого рабочий стек** | **~600MB** | |

---

## Зависимости между файлами

```
architecture_overview.md                    ← ОСНОВА
  ├── stack_specification.md                (стек)
  ├── embedding_chain_v1.3.md              (эмбеддинг)
  │
  ├── observer_specification_v1.3.md        (Observer)
  │     └── observer_patch_v1.4.md
  │
  ├── dissolver_specification_v1.3.md       (Dissolver)
  │     └── dissolver_patch_v1.4.md
  │
  ├── tuner_specification.md                (Tuner)
  │     └── tuner_specification_v1.4.md
  │
  ├── conductor_specification.md            (Conductor)
  │
  ├── api_tools_specification.md            (API v1.0)
  │     └── api_tools_specification_v2.md   (+3 мониторинг)
  │           └── api_tools_urgency_policy_v1.3.md (+2)
  │                 └── ctx_sync_load_specification.md
  │
  ├── feedback_loop_v1.5.md                 (Feedback)
  │
  ├── mnestroma_config_tuner_v1.0.md        (Config: 62 params)
  │     └── config_tuner_patch_v1.4.md      (+18 = 80 params)
  │
  ├── ADR_001_script_vs_model.md            (Script vs Model)
  │
  └── architecture_patch_v1.4.md            (embedding versioning, Score profiles)
```

---

## Roadmap

| Фаза | Что | Статус |
|------|-----|--------|
| v1.x MVP | Observer + Session Index + Dissolver + Tuner + Conductor + Content Branch + MCP API + Onboarding Pipeline | ⬜ реализация не начата |
| v1.3 | Urgency Policy + Principle protection | 📋 задокументировано |
| v1.4 | Патчи: embedding versioning, Score profiles, GLiNER dual, Content eviction | 📋 задокументировано |
| v1.5 | Implicit feedback + ExperienceCluster + базовый Subconscious Evaluator | 📋 задокументировано |
| v2.0 | Explicit feedback loop + adaptive score weights | 📋 запланировано |
| v3.0 | Hypómnema Strōma: Pattern Encoder + Anomaly Autoencoder (~11MB) | 📋 запланировано |

---

## Ключевые архитектурные решения (эта сессия, 2026-03-25)

| Решение | Обоснование |
|---------|-------------|
| WP-02 → 🟢 | async_flush 5s покрывает рабочие данные; content_full = подстраховка |
| WP-03 → 🟢 | Одна SQLite WAL; single-agent sidecar = конкуренция невозможна |
| WP-01 → 🟢 | Implicit feedback = биологически корректная реконсолидация |
| Onboarding Pipeline | Автокалибровка при первом запуске из 10-50 сессий истории чатов |
| BGE-M3 lazy load | Не загружать до первого content.save() → экономия 145MB |

---

## Недостающие документы

| Документ | Приоритет | Описание |
|----------|-----------|----------|
| `experience_layer_specification_v1.0.md` | P1 | Собрать из SESSION_BRIDGE + ADR_001 + config_tuner_patch |
| `onboarding_pipeline_specification.md` | P1 | Автокалибровка при первом запуске |
| `MNEMOSTROMA_TODO_v2.md` | P0 | Обновить с результатами этой сессии |
| `README.md` | P0 | Для GitHub, на основе двух descriptions |
| `subconscious_layer_specification.md` | P2 | Детальная спека Hypómnema Strōma (v3.0) |
| `benchmark_plan.md` | P1 | precision@5 на 100 сессиях vs MemGPT/Zep/Mem0 |
| `monetization_strategy.md` | P2 | Open-core стратегия |
| `MNESTROMA_WEAK_POINTS_v3.md` | P0 | Обновлённый анализ (создаётся вместе с этим INDEX) |

---

## Академическая база

| Источник | Что взяли |
|----------|-----------|
| LightMem (ICLR 2026) | Трёхуровневая модель + offline consolidation |
| Hindsight (Vectorize.io) | Независимые сети памяти |
| Miller (1956) | 7±2 active_variables |
| Atkinson-Shiffrin | Sensory → STM → LTM модель |
| Eisenhower Matrix | urgency × importance квадранты (v1.3) |
| Эббингауз | Кривая забывания → Dissolver exponential decay |
| Реконсолидация памяти | Implicit feedback через использование (v1.5) |

---

*Mnemostroma | INDEX v1.4 | 2026-03-25*
*Документов: 27 | Патчей v1.4: 7 | Параметров: 80 | Weak Points: 23/23 закрыты*
