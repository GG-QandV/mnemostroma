# Roadmap

## RAM-First Context System

---

## Phase 1: Core (текущая фаза)

**Цель:** полностью задокументированная и реализуемая архитектура.

### Документация (статус)

- [x] `architecture_overview.md` — полная архитектура
- [x] `stack_specification.md` — стек компонентов
- [x] `observer_specification.md` — Observer пайплайн
- [x] `api_tools_specification.md` — API инструментов
- [x] `dissolver_specification.md` — механизм растворения
- [x] `conductor_specification.md` — оркестратор и bootstrap
- [x] `tuner_specification.md` — детекторы диссонанса
- [ ] `feedback_loop_specification.md` — агент оценивает полезность контекста

### Реализация (очередь)

1. Conductor: bootstrap + event loop
2. Observer MVP (без Content branch)
3. Session Index (RAM dict + HNSWlib)
4. Dissolver: recalc + apply_layer
5. Tuner: Conflict Detector (первый)
6. API: ctx.active, ctx.get, ctx.semantic, ctx.status
7. Тест: загрузить 100 сессий → ctx.semantic() → проверить precision@5

### MVP критерий готовности

```
- ctx.active() возвращает корректный bridge
- ctx.semantic("запрос") находит релевантные сессии за < 25ms
- Observer обрабатывает output агента за < 30ms async
- После перезапуска: система восстанавливается из SQLite корректно
- RAM не превышает 600MB при 200 сессиях
```

---

## Phase 2: Cloud Sync (опциональный слой)

**Цель:** синхронизация между машинами и командная память.

### Архитектурные решения (зафиксированы)

- Синхронизируются ТОЛЬКО холодные слои: SQLite_Archive + SQLite_Eternal
- RAM Hot/Warm никогда не покидают машину
- Latency основной системы не затрагивается
- E2E шифрование обязательно

### Открытые вопросы (требуют решения)

- Conflict resolution при синхронизации между машинами
- Механизм E2E шифрования (ключ на устройстве vs. derived key)
- PWA как альтернатива нативным мобильным клиентам

### Бизнес-модель

| Tier       | Что                                | Цена           |
| ---------- | ---------------------------------- | -------------- |
| Local Free | Полный daemon, офлайн, без лимитов | бесплатно      |
| Sync Pro   | Cloud sync между машинами + бэкап  | $8-12/мес      |
| Team       | Shared context для команды агентов | $20-40/мес/чел |
| Enterprise | Self-hosted облако, свои модели    | контракт       |

Модель: **Obsidian Sync** — продукт бесплатный локально, платишь только за синхронизацию.

---

## Phase 3: Mobile Thin Clients

**Цель:** чтение контекста с мобильных устройств.

### Архитектурные решения (зафиксированы)

- Мобильные = только Thin Client (чтение + базовый поиск)
- Полный ONNX стек (342MB) на телефоне — нецелесообразно
- Требуют работающего Cloud Sync Layer (Phase 2)

### Android

- Python + ONNX Runtime Android (официально поддерживается)
- SQLite нативный
- Thin Client: только ctx.active, ctx.search, ctx.pulse
- Та же кодовая база что desktop (Python)

### iOS

- **Отдельная кодовая база** (Swift + ONNX Runtime iOS SDK)
- Python запрещён Apple (JIT execution policy)
- Только Thin Client через REST API Cloud Sync Layer
- ctx.active, ctx.search, ctx.pulse — нативный Swift

### Открытые вопросы

- Нужен ли офлайн-режим на Android (полный стек 342MB на флагманах)?
- PWA как промежуточный вариант до нативных приложений?

---

## Зафиксированные решения (все фазы)

### Архитектура

1. Тип софта: **Memory Sidecar Daemon**
2. Протокол IDE-интеграции: JSON-RPC 2.0 (модель LSP)
3. Холодный старт: HNSWlib из ВСЕХ embeddings, RAM ← последние N по Score
4. N адаптивный: дефолт 200, soft 380MB, hard 480MB, минимум 50
5. Lazy load при miss в RAM (не preload)
6. Бинарник собирается через PyInstaller / Nuitka

### Платформы

7. Linux / macOS: Unix Socket
8. Windows: Named Pipe
9. iOS требует отдельной Swift кодовой базы
10. Android — та же кодовая база (Python)

### Мониторинг (новые API инструменты)

11. `ctx.status()` — расширенный ASCII дашборд
12. `ctx.growth()` — рост данных + прогноз исчерпания
13. `ctx.pulse()` — одна строка для логов, <0.01ms
