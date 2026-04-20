# Mnemostroma — TODO
> v3.2 | 2026-04-07 | Обновлено после завершения Фазы 9.2

---

## P0 — Блокеры публичного запуска
- [x] **Safe/debug режим логирования**: `logs.db` по умолчанию пишет детальные события. Нужно добавить флаг `logging.enabled: false` в `config.json` и реализовать его проверку в `LogWriter`. (DONE)
- [x] **`mnemostroma install-models` CLI**: скрипт для автоматической загрузки финального стека моделей (E5, DistilBERT, TinyBERT). (DONE)
- [x] **Очистка репозитория**: удаление `core.py.old`, `pure_gliner.py`, `_backup_refactor_.../` и неиспользуемых моделей из `models/`. (DONE)
- [x] **Синхронизация веток**: привести `alpha` ветку в соответствие с `main` (публичная политика). (DONE)

---

## P1 — Завершение Observer (Phase B)
- [x] **B.2: `continuation_detector.py`**: реализация логики продолжения сущностей (cosine × 0.7 + tags × 0.1 + recency × 0.2). (DONE)
- [x] **B.3: `mention_type` classifier**: разделение сущностей на "focus" (основная тема) и "passing" (упоминание вскользь). (DONE)
- [x] **Исправить placeholders**: `pipeline.py:166-169` содержит захардкоженные флаги якорей. (DONE)
- [x] **Reranker Integration Test**: верифицировать работу `tinybert-l2-v2` с эмбеддингами dim=384. (DONE)
- [x] **Awaiting Persistence**: `create_task(...)` → `await ctx.persistence.*` во всех критических местах. (DONE)

---

## P2 — Новые слои и архитектура
- [x] **PersistenceLayer/WorkingMemory Split (Phase 9.2)**: формальное разделение слоёв через интерфейс. (DONE)
- [x] **CLI setup/on/off/status + config_default.json**: пользовательский режим управления демоном. (DONE)
- [x] **Experience Layer**: реализация кластеров опыта и генерация `intuition_signal`. (DONE)
- [x] **Onboarding Pipeline**: автокалибровка порогов на основе 10-50 сессий исторического контекста. (DONE)
- [x] **Decay Engine (Stage C)**: фоновый процесс "растворения" неактуальных связей. (DONE)
- [x] **Session Bridge**: полноценная реализация `ctx.bridge()` для бесшовной передачи контекста. (DONE)

---

## P3 — Оптимизация и инструменты
- [x] **RAM Health Check**: реализовано через `psutil` в `conductor.py` (v1.7.0).
- [ ] **Config Tuner UI**: графический или CLI интерфейс для настройки 80+ параметров.
- [ ] **Benchmarks**: выполнение плана тестирования precision@5.

---

## Статус по слоям (Факт на 2026-04-07)

| Слой | Спека | Реализация | Версия | Статус |
|------|-------|------------|--------|--------|
| **Memory Layer** | ✅ v1.3 + патчи | ✅ v1.7.1 | 303 теста | Full (numpy) |
| **Persistence** | ✅ Phase 9.2 | ✅ v1.7.1 | — | formal split |
| **Anchor Layer** | ✅ (в specs) | ✅ v1.7.x | — | Full (marker) |
| **Feedback Loop** | ✅ v1.5 | ✅ v1.5.0 | — | Implicit |
| **MCP API** | ✅ v2 | ✅ v1.7.0 | — | 16 tools |
| **Observer Phase B** | ✅ согласована | ✅ v1.7.0 | — | B.1..B.3 done |
| **Experience Layer** | ✅ v1.0 | ✅ v1.7.0 | — | Clusters done |
| **Subconscious** | ⚠️ placeholder | ✅ v1.7.0 | Stage C/D | Decay/Dreamer |
| **Onboarding** | ✅ v1.0 | ✅ v1.7.0 | — | Stage 0 done |

---

## Резюме аудита
Система ядра (Observer → Storage → Index) стабильна и покрыта 303 тестами. Реализован формальный PersistenceLayer, устранены риски fire-and-forget при записи. CLI инструменты `setup/on/off/status` готовы к использованию в User Mode.

---

*Mnemostroma TODO | v3.2 | 2026-04-07*
