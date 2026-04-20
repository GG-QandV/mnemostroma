# Инструкция для агента: обновление документации Mnemostroma
> Версия: 1.0 | 2026-04-01  
> Составлена по результатам аудита Аудит_Клауде_Мнемострома_2026-04-01.md  
> Для выполнения в отдельном IDE / агентской сессии

---

## Контекст задачи

Проект Mnemostroma — автономный RAM-first слой когнитивной памяти для AI-агентов.  
Репозиторий: `~/projects/Project_mnemostroma/`

**Проблема:** документация отстаёт от реализации на ~1 месяц.  
- `INDEX_v4.md` написан 2026-03-25 и утверждает "реализация не начата"
- Реальность: v1.6.2, 79/79 тестов, ~80% MVP реализовано (17 коммитов)
- Стратегические документы упоминают EmbeddingGemma, код использует E5-small

**Твоя задача:** привести все документы в соответствие с реальным состоянием кода и добавить недостающие документы.

---

## Перед началом работы — обязательно прочитай

1. `docs/Аудит_Клауде_Мнемострома_2026-04-01.md` — полный аудит (главный источник истины)
2. `archive of documents/Mnemostroma Session Context Transfer v3.md` — история разработки
3. `CHANGELOG.md` — хронология версий
4. `src/mnemostroma/` — реальный код (истина выше любого документа)
5. `models_manifest.json` — актуальный стек моделей

---

## БЛОК A — Обновить существующие документы

### A-1. `INDEX_v4.md` → создать `INDEX_v5.md`

**Что изменить:**

**Таблица Roadmap** (сейчас все строки "⬜ реализация не начата"):
```
# БЫЛО:
v1.x MVP | Observer + Session Index + Dissolver + ... | ⬜ реализация не начата

# СТАЛО (реальный статус):
v1.6.2 | Observer, HybridNER, HNSW, Dissolver, Tuner, Conductor, MCP, Anchor, Feedback | ✅ реализовано
B.2/B.3 | continuation_detector, mention_type | 🔄 в процессе
Decay Engine (C) | фоновое забывание | ⬜ не начато
Dreamer (D) | фоновая переоценка | ⬜ не начато
Experience Layer | +/- кластеры, intuition_signal | ⬜ не начато
Onboarding Pipeline | автокалибровка | ⬜ не начато
```

**Таблица стека** (обновить под финальный v3):
```
| Роль | Модель | dim | Файл | RAM |
| session_embedder | multilingual-e5-small int8 | 384 | models/multilingual-e5-small/onnx/model_int8.onnx | ~420MB |
| content_embedder | multilingual-e5-small int8 | 384 | (shared с session) | — |
| NER | HybridNER (DistilBERT + regex) | — | models/distilbert-ner/onnx/model_int8.onnx | ~170MB |
| Reranker | TinyBERT-L2-v2 | — | models/tinybert-l2-v2/onnx/model_quint8_avx2.onnx | lazy |
| TOTAL RSS | | | | 631MB |
```

**Удалить строки:** упоминания EmbeddingGemma-300m и BGE-M3 как активных моделей (они не в manifest).

**Обновить раздел "Недостающие документы":**
- Убрать уже созданные (README, README_RU, WEAK_POINTS_v3, TODO_v2)
- Добавить реально недостающие (см. Блок B)

**Обновить дату:** v1.5 → 2026-04-01

**Сохранить как:** `INDEX_v5.md` (не удалять v4, он архив)

---

### A-2. `MNEMOSTROMA_TODO_v2.md` → создать `MNEMOSTROMA_TODO_v3.md`

**Что изменить:**

**Таблица "Статус по слоям"** — полностью переписать:
```markdown
| Слой | Спека | Реализация | Версия |
|------|-------|------------|--------|
| Memory Layer (Observer + HNSW + Dissolver + Tuner) | ✅ v1.3 + патчи v1.4 | ✅ v1.6.2 | 79 тестов |
| Anchor Layer | ✅ (в conductor/subconscious specs) | ✅ v1.6.x | — |
| Feedback Loop (implicit) | ✅ v1.5 | ✅ v1.5.0 | — |
| MCP API (18+ инструментов) | ✅ v1.3 + v2 | ✅ частично | требует аудит покрытия |
| Config Tuner (80 params) | ✅ | ⬜ не начат | — |
| Experience Layer | ⚠️ разрознен по файлам | ⬜ не начат | нужна спека v1.0 |
| Subconscious Layer (Decay + Dreamer) | ⚠️ placeholder | ⬜ не начат | v3.0 план |
| Onboarding Pipeline | ⬜ нужна спека | ⬜ не начат | — |
| Session Bridge | ✅ спека в ctx_sync_load | ⬜ не начат | — |
| B.2 continuation_detector | ✅ согласована в архиве | ⬜ не начат | — |
| B.3 mention_type | ⬜ нет спеки | ⬜ не начат | — |
```

**Раздел P0 — обновить:**
```markdown
## P0 — Блокеры публичного запуска
- [ ] Safe/debug режим логирования (logs.db по умолчанию = риск для offline/privacy positioning)
- [ ] `mnemostroma install-models` CLI (без этого пользователь не может установить)
- [ ] Очистка репо (core.py.old, pure_gliner.py, backup папки, неиспользуемые модели)
- [ ] Синхронизация ветки alpha с main (политика public branch)
```

**Раздел P1 — обновить:**
```markdown
## P1 — Завершение Observer
- [ ] B.2 continuation_detector.py (архитектура готова, код не написан)
- [ ] B.3 mention_type classifier
- [ ] Аудит покрытия MCP инструментов (18+ по спеке)
- [ ] Session Bridge (ctx.bridge())
- [ ] Исправить placeholder anchor.flags в pipeline.py:166-169
```

**Сохранить как:** `MNEMOSTROMA_TODO_v3.md`

---

### A-3. `CHANGELOG.md` — добавить записи

Добавить в начало файла (после `## [1.6.2]`):

```markdown
## [Unreleased] — в процессе

### Planned
- B.2: continuation detection (HNSW + tags + recency combined scoring)
- B.3: mention_type (focus vs passing)
- Safe/debug logging mode
- mnemostroma install-models CLI
- Decay Engine (Stage C)
```

---

### A-4. `README.md` — обновить статус

**Найти раздел со статусом** (или добавить если нет):

```markdown
## Status

**Current:** v1.6.2 alpha

| Component | Status |
|-----------|--------|
| Core backend (Observer, Memory, Storage) | ✅ Implemented, 79/79 tests |
| Anchor Layer | ✅ Implemented |
| Implicit Feedback (v1.5) | ✅ Implemented |
| MCP Server (stdio) | ✅ Implemented |
| Continuation Detection (B.2) | 🔄 Architecture ready, implementation pending |
| Decay Engine | ⬜ Planned |
| Dreamer | ⬜ Planned |
| Experience Layer | ⬜ Planned |
| Model install CLI | 🔄 In progress |

> Alpha: model setup requires manual steps. See [Model Setup](#model-setup).
> Local diagnostics (`logs.db`) are written by default during alpha. See [Logging](#logging).
```

**Добавить раздел "Model Setup"** (если нет):
```markdown
## Model Setup

After `pip install mnemostroma`:

```bash
# Download required models (~300MB)
mnemostroma install-models
```

Models are downloaded from Hugging Face. Some may require account/license acceptance.  
See `stack_download_manifest.md` for details.

**Required models:**
- `multilingual-e5-small` (E5 int8, 384d) — session & content embedder
- `distilbert-ner` (DistilBERT int8) — HybridNER
- `tinybert-l2-v2` (TinyBERT, lazy) — reranker
```

**Добавить раздел "Logging"** (если нет):
```markdown
## Logging

Mnemostroma writes local diagnostic logs to `logs.db` during alpha.  
Logs contain: startup events, model load times, tool calls, error states.  
**Logs never leave your machine.** No network calls.

To disable:
```json
// config.json
"logging": { "enabled": false }
```
```

---

### A-5. `architecture_overview.md` — обновить стек моделей

**Найти** секцию с моделями (EmbeddingGemma, BGE-M3) и заменить на финальный стек v3:

```markdown
## Model Stack (Final v3, 2026-03-31)

| Role | Model | Dim | File | RAM |
|------|-------|-----|------|-----|
| Session & Content Embedder | multilingual-e5-small int8 | 384 | models/multilingual-e5-small/ | ~138MB ONNX + ~270MB tokenizer |
| NER | HybridNER (DistilBERT + regex) | — | models/distilbert-ner/ | ~178MB |
| Reranker | TinyBERT-L2-v2 | — | models/tinybert-l2-v2/ | 8MB (lazy) |
| **Total RSS** | | | | **631MB** |

Budget: 700MB hard limit. Margin: 69MB.

Note: EmbeddingGemma-300m and BGE-M3 were evaluated during design phase
but replaced by E5-small for practical ONNX availability and licensing reasons.
```

---

### A-6. `stack_specification.md` — обновить под реальный стек

Аналогично A-5: заменить все упоминания EmbeddingGemma и BGE-M3 как "активных" на исторические примечания. E5-small = актуальный выбор.

---

### A-7. `MNESTROMA_WEAK_POINTS_v3.md` — добавить раздел

Добавить в конец файла новый раздел:

```markdown
## Дополнение v3.1 — Аудит реализации 2026-04-01

После аудита реализации выявлены новые weak points уровня реализации
(не архитектурные — архитектура по-прежнему ✅):

| ID | Пункт | Уровень | Статус |
|----|-------|---------|--------|
| R-01 | placeholder anchor.flags в pipeline.py:166-169 | 🟡 | ⬜ исправить в B.2 |
| R-02 | RAM health check = 0.0 в conductor.py | 🟢 | ⬜ заменить на psutil |
| R-03 | Reranker интеграция с dim=384 не верифицирована | 🟡 | ⬜ добавить E2E тест |
| R-04 | Нет safe/debug режима логирования | 🟡 | ⬜ Фаза 1.1 |
| R-05 | Нет install-models CLI | 🟡 | ⬜ Фаза 1.2 |
```

---

## БЛОК B — Создать новые документы

### B-1. `experience_layer_specification_v1.0.md` — СОЗДАТЬ

**Источники для сборки** (прочитать все перед написанием):
- `archive of documents/Mnemostroma Session Context Transfer v3.md` (раздел Experience Layer)
- `archive of documents/Cosed_docs_git_ignore/Experience-Subconscious_Mnemostroma.md`
- `ADR_001_script_vs_model.md`
- `config_tuner_patch_v1.4.md` (секция Experience Layer параметры)
- `SESSION_BRIDGE_2026_03_09.md`

**Структура документа:**
```markdown
# Experience Layer Specification v1.0

## Цель
## Место в архитектуре (между Memory и Subconscious)
## ExperienceCluster
  - +Experience Index / -Experience Index
  - maturity: novice → apprentice → practitioner → expert → master
## Intuition Signal
  - DO_THIS / AVOID_THIS / TENSION
  - Когда генерируется
  - Как передаётся агенту
## MCP API
  - ctx.growth() — текущий уровень опыта по категориям
  - ctx.pulse() — активные intuition signals
## Связь с Observer
  - Какие события Observer обновляют Experience
## Связь с Dissolver
  - Как Dissolver влияет на опыт (decay vs reinforcement)
## Параметры в config_tuner
## Roadmap реализации
```

---

### B-2. `onboarding_pipeline_specification.md` — СОЗДАТЬ

**Что описать:**
```markdown
# Onboarding Pipeline Specification

## Цель
Автокалибровка системы при первом запуске на основе
10-50 сессий исторических данных агента.

## Шаг 0 Bootstrap
  - Определение: первый запуск = mnemostroma.db пустая
  - Источники истории: Claude export / custom import format
  - Минимум: 10 сессий; оптимум: 50 сессий

## Калибровочный агент
  - Прогон истории через Observer pipeline
  - Сбор статистик: типичные теги, типичный score, NER распределение
  - Результат: обновлённый config.json с откалиброванными порогами

## Параметры для калибровки
  - ner_call_rate threshold
  - tag_score_threshold (0.5 по умолчанию)
  - dissolver decay rates
  - session_type_classifier baseline

## Интеграция с Conductor
  - Добавить шаг "0.5" в bootstrap sequence
  - Пропускать если БД уже содержит > min_sessions

## MCP скилл (опционально)
  - ctx.calibrate(history_path) → запуск onboarding pipeline
```

---

### B-3. `benchmark_plan.md` — СОЗДАТЬ

```markdown
# Mnemostroma — Benchmark Plan

## Цель
Публичное сравнение precision@5 vs MemGPT, Zep, Mem0 на 100 сессиях.

## Методология
  - 100 синтетических сессий (разные домены: tech, personal, work)
  - Метрика: precision@5 (topK retrieval по семантическому запросу)
  - Метрика: latency p50/p95/p99 (мс)
  - Метрика: RAM usage

## Датасет
  - Генерация: скрипт tests/generate_benchmark_sessions.py
  - Покрытие: 5 доменов × 20 сессий
  - Разметка ground truth: ручная + LLM-assist

## Сравниваемые системы
  - Mnemostroma (этот проект)
  - MemGPT (mem0.ai)
  - Zep
  - Mem0
  - Baseline: naive last-N context window

## Результаты
  - Таблица в README
  - Подробный отчёт в docs/benchmark_results.md
```

---

### B-4. `docs/CONTEXT_TRANSFER_v5.md` — СОЗДАТЬ (актуальный transfer)

**Важно:** Это замена устаревшему `Mnemostroma Session Context Transfer v3.md` в архиве.  
Цель: актуальный файл переноса контекста для следующих сессий разработки.

**Структура:**
```markdown
# Mnemostroma Session Context Transfer v5
> 2026-04-01 | v1.6.2 | 79 tests

## Расположение
## Финальный стек моделей (v3)
## Архитектура (4 уровня)
## Реализованные модули (список)
## НЕ реализовано (приоритизировано)
## Закрытые баги (B01-B25+)
## Ключевые контракты (API сигнатуры)
## Команды запуска/тестов
## Приоритет следующей сессии
```

Заполнить из:
- `docs/Аудит_Клауде_Мнемострома_2026-04-01.md`
- `docs/ROADMAP_архитектура_2026-04-01.md`
- `archive/.../Mnemostroma Session Context Transfer v3.md` (разделы закрытых багов)

---

## БЛОК C — Проверить и привести в порядок

### C-1. Проверить `deployment_guide.md`
- Соответствует ли инструкция реальной структуре репо?
- Есть ли раздел про `mnemostroma install-models`? Если нет — добавить placeholder
- Пути к моделям актуальны?

### C-2. Проверить `security_specification.md`
- Добавить раздел про `logs.db`: что пишется, как отключить, гарантия локальности

### C-3. Проверить `embedding_chain_v1.3.md`
- Убрать упоминание GTE-768d как "текущего" — заменить на E5-small-384d
- Описать переход 768→384 как архитектурное решение (не ошибку)

### C-4. Проверить `conductor_specification.md`
- Сверить 10 шагов bootstrap с реальным `conductor.py`
- Добавить шаги B0.5 (dim migration) и B0.6 (anchor hydration) которые есть в коде

---

## БЛОК D — НЕ трогать (архивные документы)

Следующие файлы — архив, не обновлять:
- `INDEX_v2.md`, `INDEX_v3.md`, `INDEX_v4.md`
- `MNEMOSTROMA_TODO_v1.md`, `MNEMOSTROMA_TODO_v2.md`
- `MNESTROMA_WEAK_POINTS_v2.md`
- `dissolver_specification.md` (v1.1 архив)
- `observer_specification.md` (v1.0 архив)
- `mnestroma_Config_tuner.md` (дубль)
- Всё в `archive of documents/`

---

## Порядок выполнения

1. Прочитать все файлы из раздела "Перед началом работы"
2. Выполнить **Блок A** в порядке A-1 → A-7
3. Выполнить **Блок B** (можно параллельно B-1, B-2, B-3)
4. Выполнить **Блок C** (проверки)
5. Создать `docs/CONTEXT_TRANSFER_v5.md` последним (B-4) — он суммирует всё

**Не изменяй исходный код** — только документация.  
**Не удаляй** архивные файлы — только добавляй новые версии.  
**Проверяй код** перед написанием — истина в `src/`, а не в старых доках.

---

*Инструкция для агента | v1.0 | 2026-04-01 | составлена на основе аудита*
