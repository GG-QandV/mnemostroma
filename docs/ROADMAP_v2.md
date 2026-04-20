# Mnemostroma — Roadmap v2

> Обновлён: 2026-04-07 | Предыдущая версия: 2026-04-04
> Текущая версия кода: v1.7.x (post-v1.6.2)

---

## Статус реализации

| Фаза | Содержание | Статус |
|------|------------|--------|
| 1 | HNSW → numpy MatrixSearch (ADR-002) | ✅ Сделано |
| 2 | marker() / Entity / Emotion / Atmosphere | ✅ Сделано |
| 3 | Anchor Decay Engine | ✅ Сделано |
| 4 | Dreamer (idle + reassessment) | ✅ Сделано |
| 5.1 | Temporal Relations Graph (t_rel) | ✅ Сделано |
| 5.2 | Pending Emotion Resolution | ✅ Сделано |
| 5.3 | RAM Eviction Formula v2 | ✅ Сделано |
| 5.4 | Emotional Patterns Layer | ✅ Сделано |
| 6.1 | MCP API Audit (16 tools, tests) | ✅ Сделано |
| 6.2 | Reranker E2E Test | ✅ Сделано |
| 9.1 | Persistence P1: QueueFull метрика + experience await | ✅ Сделано |
| 9.2 | PersistenceLayer / WorkingMemory formal split | ✅ Сделано |
| CLI | setup/on/off/status + config_default.json | ✅ Сделано |
| — | Daemon Infrastructure | ✅ Сделано |
| 7 | Doc Updates | ⏳ Другой агент |
| 8 | Benchmarks | ⏳ Отложено (~2 мес) |

---

## Что реализовано (v1.7.x)

- **Observer pipeline**: filter → HybridNER → compress → embed → score → anchor → save
- **marker()**: Entity / Emotion / Atmosphere классификация, TemporalMarker, TemporalRelations
- **Continuation Detector**: cosine×0.7 + tags×0.1 + recency×0.2
- **Anchor Layer**: AnchorIndex, decay_level, t_rel персистентность, check_anchor_schema() миграция
- **Anchor Decay**: ConsolidationWorker, apply_decay() по уровням 0→3, pin_protection
- **Dreamer**: idle detection, фоновый пересмотр outcome, resurface по access_count
- **Pending Emotion Resolution**: pending_emotions в SystemContext, resolve_pending_emotions()
- **Emotional Patterns**: ExperienceCluster emotion_positive/negative/intensity_sum, ATTRACT/REPEL/AMBIVALENT сигналы
- **RAM Eviction**: priority = importance × (1 + intensity) × recency_factor
- **Matrix Search**: numpy cosine similarity, _rebuild_session_index() после eviction
- **MCP**: 16 агентских инструментов, daemon-only убраны, KeyError handler, тесты routing+coverage
- **Daemon Infra**: PulseWriter (5s), StatusWriter (30s), DBManager.flush(), SIGUSR1/2, CLI dump/growth
- **SDK**: build_memory_context() для оркестраторов
- **Experience Layer**: ExperienceCluster, maturity, intuition_signals (DO_THIS/AVOID_THIS/TENSION/ATTRACT/REPEL/AMBIVALENT)
- **Config Tuner CLI**: mnemostroma config list/get/set
- **Tools**: mnemostroma watch / tray / logs / dump / growth / setup / on / off / status
- **PersistenceLayer**: формальный сплит WorkingMemory/SQLite, await для критических записей (9.2)

---

## Открытые задачи

### ⏳ Фаза 7 — Doc Updates (отдельный агент)

Передать контекст через CM: `cm_search("doc update task roadmap v2 mnemostroma")`

Файлы для обновления: `CHANGELOG.md`, `MNEMOSTROMA_TODO_v3.md`,
`MNESTROMA_WEAK_POINTS_v3.md`, `INDEX_v5.md`,
`instructions/AGENT_CODING_INSTRUCTIONS.md`,
`instructions/logging_specification.md`, `architecture_overview.md`,
`stack_specification.md`, `ADR_001_script_vs_model.md`.
Создать: `docs/CONTEXT_TRANSFER_v5.md`, `CHANGELOG.md` v1.7.0 запись.

### ⏳ Фаза 8 — Benchmarks (~2 мес)

precision@5 vs MemGPT / Zep / Mem0, latency p50/p95/p99, RAM footprint.
Синтетический датасет: 100 сессий × 5 доменов с ground truth.

---

### *Roadmap v2 | обновлён 2026-04-07*
