# Mnemostroma — TODO
> v2.0 | 2026-03-25 | Обновлено после аудита + разбора weak points

---

## P0 — Блокеры реализации

- [x] `INDEX_v4.md` — мастер-индекс v1.4 ✅ создан 2026-03-25
- [x] `README.md` — для GitHub (EN) ✅ создан 2026-03-25
- [x] `README_RU.md` — русская версия ✅ создан 2026-03-25
- [x] `MNESTROMA_WEAK_POINTS_v3.md` — пересмотренный анализ, 33/33 закрыты ✅
- [ ] `implementation_guide.md` — порядок реализации, минимальный скелет, что пропустить
- [ ] `data_flow_specification.md` — сквозной путь данных write/read через всю систему

---

## P1 — Важно для реализации

- [ ] `onboarding_pipeline_specification.md` — автокалибровка из 10-50 сессий при первом запуске
- [ ] `experience_layer_specification_v1.0.md` — собрать из SESSION_BRIDGE + ADR_001 + patches
- [ ] `benchmark_plan.md` — precision@5 vs MemGPT/Zep/Mem0 на 100 сессиях
- [ ] `mnemostroma_description_technical_v2.md` — функционал без деталей реализации

---

## P2 — После позиционирования

- [ ] `subconscious_layer_specification.md` — Hypómnema Strōma (v3.0)
- [ ] `monetization_strategy.md` — open-core: local free / sync pro / enterprise
- [ ] `brand.md` — этимология, слоган, домены
- [ ] `cloud_sync_specification.md` — conflict resolution, E2E encryption
- [ ] Массовая замена "RAM-First Context System" → "Mnemostroma" во всех файлах

---

## Архитектурные решения этой сессии (2026-03-25)

| Решение | Детали |
|---------|--------|
| WP-01 Feedback → 🟢 | Implicit feedback = биологически корректная реконсолидация |
| WP-02 Crash → 🟢 | async_flush 5s защищает рабочие данные; content_full = подстраховка |
| WP-03 SQLite → 🟢 | Одна БД + WAL; single-agent sidecar, конкуренция невозможна |
| Onboarding Pipeline | Автокалибровка из 10-50 сессий истории; шаг 0 в Conductor bootstrap |
| BGE-M3 lazy load | Не загружать до первого content.save(); параметр в config_tuner |
| Калибровочный агент | MCP-скилл / встроенный в Conductor; прогон истории → config.json |

---

## Статус по слоям системы

| Слой | Спека | Патчи | Реализация |
|------|-------|-------|------------|
| Memory Layer v1.3 | ✅ полная | ✅ v1.4 | ⬜ не начата |
| Experience Layer | ⚠️ не собран в файл | — | ⬜ не начата |
| Subconscious Layer | ⚠️ placeholder | — | ⬜ v3.0 |
| Config Tuner (80 params) | ✅ полная | ✅ v1.4 | ⬜ не начата |
| Conductor | ✅ полная | — | ⬜ не начата |
| API (18+ инструментов) | ✅ полная | — | ⬜ не начата |
| Feedback Loop v1.5 | ✅ implicit | — | ⬜ не начата |
| Onboarding Pipeline | ⬜ нужна спека | — | ⬜ не начата |
| Документация публичная | ✅ README готов | — | — |

---

## Рекомендованный порядок реализации (из implementation_guide)

```
1. Conductor bootstrap (скелет + config loading)
2. Observer pipeline (фильтр → GLiNER → embed → Score → save)
3. Session Index (RAM dict + HNSWlib)
4. SQLite WAL (sessions, anchors, precision_log)
5. MCP read tools (ctx.active, ctx.get, ctx.search, ctx.semantic)
6. Dissolver (recalc + apply_layer + 5 слоёв)
7. Tuner (Conflict Detector — остальные позже)
8. Content Branch (content_blocks + versions + BGE-M3 lazy)
9. Session Bridge (ctx.bridge)
10. Onboarding Pipeline (шаг 0 bootstrap)
```

---

*Mnemostroma TODO | v2.0 | 2026-03-25*
