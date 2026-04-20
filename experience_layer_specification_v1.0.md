# Experience Layer Specification v1.0
> μνήμη + στрῶμα | Stage: Specification | 2026-04-01

---

## 1. Цель
Experience Layer (слой опыта) предназначен для накопления долгосрочных поведенческих паттернов и генерации "интуитивных сигналов" (Intuition Signals) для агента. В отличие от Memory Layer, который хранит эпизоды, Experience Layer хранит обобщенную статистику успешности и предпочтений.

## 2. Место в архитектуре
Слой опыта находится между **Memory Layer** (оперативные знания) и **Subconscious Layer** (глубокие паттерны).

```
Memory (Episodes) → Experience (Clusters & Trends) → Subconscious (Irreducible Skeletons)
```

## 3. ExperienceCluster
Опыт группируется в кластеры по тематикам (тегам). Каждый кластер имеет показатель **maturity** (зрелость):

- **novice**: < 5 сессий по теме
- **apprentice**: 5-10 сессий
- **practitioner**: 10-30 сессий
- **expert**: 30-100 сессий
- **master**: > 100 сессий

Каждое взаимодействие с кластером через `ctx.save()` или `ctx.search()` обновляет **Experience Index** (+/- Score):
- Успешный `USE`: +1.0
- `DEEP_USE`: +2.5
- `IGNORE`: -0.5
- `CONFLICT`: -1.5 (требует ревизии)

## 4. Intuition Signal
Автоматически генерируемый контекстный блок, который подмешивается в `ctx.active()`.

| Сигнал | Условие | Сообщение агенту |
|--------|---------|------------------|
| **DO_THIS** | Cluster maturity > expert + Positive trend | "Это проверенный паттерн для этой задачи..." |
| **AVOID_THIS** | maturity > practitioner + Negative trend | "Обычно это приводит к ошибкам [A, B] в этом проекте..." |
| **TENSION** | High conflict rate в кластере | "В этой теме есть неразрешенные противоречия..." |

## 5. MCP API
- `ctx.growth()`: возвращает список активных кластеров и их уровень maturity.
- `ctx.pulse()`: возвращает текущие активные intuition signals для текущего контекста.

## 6. Связь с Observer и Dissolver
- **Observer**: при обнаружении повторяющихся тегов обновляет веса в SQLite таблице `experience_metrics`.
- **Dissolver**: если кластер не обновлялся > 90 дней, его maturity начинает снижаться (forgetting curve).

## 7. Параметры в config_tuner
- `exp_maturity_step`: 0.1
- `exp_signal_threshold`: 0.75
- `exp_decay_rate`: 0.01 (per day)

## 8. Roadmap реализации
1. Создание схемы `experience_metrics` в SQLite.
2. Реализация логики накопления maturity в `Observer.pipeline`.
3. Реализация генератора сигналов в `ConductorProxy`.
4. Интеграция с `ctx.active()`.

---
*Mnemostroma Experience Layer Spec | v1.0 | 2026-04-01*
