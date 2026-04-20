# Инструменты чтения - API спецификация
## RAM-First Context System v1.7.1
> Обновлено: 2026-04-07 | Phase 9.2 Complete

---

## 1. Принцип доступа

Все инструменты чтения - только RAM (dict или numpy MatrixSearch).
SQLite вызывается только для `ctx.full()` и `content.raw()`.

```
Уровень 1 (RAM dict):    <0.01ms   ctx.active, ctx.get, ctx.search,
                                    ctx.anchors, ctx.precision
Уровень 2 (MatrixSearch): <1ms      ctx.semantic, content.semantic (ANN)
Уровень 3 (ANN+RAM):      <2ms      ctx.semantic + brief lookup
Уровень 4 (SQLite):       <0.5ms    ctx.full, content.raw
```

Агент всегда начинает с `ctx.active()` - бесплатный мгновенный контекст.

---

## 2. Сессионный контекст

### ctx.active() -> SessionBridge
Возвращает текущий session bridge.
```python
{
    "context_brief":   str,          # одна строка, текущий фокус
    "intent_summary":  str,          # цель пользователя
    "active_variables": list[str],   # до 9 элементов (закон Миллера)
    "open_issues":     list[str],    # нерешённые конфликты
    "last_decisions":  list[str],    # последние critical decisions
    "precision_items": list[dict],   # важные прецизионные данные (URL, ссылки)
    "next_action":     str | None,
}
```

### ctx.get(session_id) -> SessionBrief
Быстрый доступ к сессии из RAM dict.
```python
{
    "session_id": str,
    "tags":       list[str],
    "brief":      str,      # max 50 символов
    "importance": str,      # critical / important / background
    "age_signal": str,      # fresh / actual / stale / archive
    "score":      float,
    "anchors":    list[dict],
    "conflict":   bool,
    "layer":      str       # RAM_HOT / RAM_WARM / DISK
}
```

### ctx.search(tags, importance=None, age=None, limit=10)
Фильтрация по тегам в RAM dict. Без ML, поиск по вхождению.
Пример: `ctx.search(["#решение", "#архитектура"], importance="critical")`

### ctx.semantic(query, top_k=5, rerank=True) -> list[SessionBrief]
Полный пайплайн: embed(10ms) -> MatrixSearch(0.5ms) -> TinyBERT rerank(6ms) -> RAM brief(0.01ms)
Итого ~17-20ms.

---

## 3. Контентная ветка

### content.search(query, project_id=None, status="active", top_k=5)
MatrixSearch Content поиск + RAM brief lookup.
```python
[{
    "content_id":    str,
    "content_type":  str,
    "version":       int,
    "content_tags":  list[str],
    "why_changed":   str,
    "status":        str,
    "score":         float,
}]
```

### content.raw(content_id, version=None) -> str [SQLite]
Полный текст контента. lz4 decompress + SQLite. ~2ms.

---

## 4. Управление (v1.7.1)

| Инструмент | Операция |
|---|---|
| ctx.status() | RAM usage, кол-во сессий, latency stats, Persistence status |
| ctx.sync() | Принудительный flush pending PersistenceLayer операций |
| ctx.load(session_id) | Загрузить архивную сессию из SQLite в RAM |

---

*Mnemostroma | API Specification | v1.7.1 | 2026-04-07*
*μνήμη + στρῶма · ~20ms · 303 tests*
