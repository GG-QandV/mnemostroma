# Инструменты чтения - API спецификация
## RAM-First Context System v1.0

---

## 1. Принцип доступа

Все инструменты чтения - только RAM или RAM+HNSWlib.
SQLite вызывается только для ctx.full() и content.raw().

```
Уровень 1 (RAM dict):    <0.01ms   ctx.active, ctx.get, ctx.search,
                                    ctx.anchors, ctx.precision
Уровень 2 (HNSWlib):     <2ms      ctx.semantic, content.semantic
Уровень 3 (HNSWlib+RAM): <2ms      ctx.semantic + brief lookup
Уровень 4 (SQLite):      <0.5ms    ctx.full, content.raw
```

Агент всегда начинает с ctx.active() - бесплатный мгновенный контекст.

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
    "precision_items": list[dict],   # важные прецизионные данные
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
    "importance": str,
    "age_signal": str,
    "score":      float,
    "anchors":    list[dict],
    "conflict":   bool,
    # НЕ content_full - для этого ctx.full()
}
```

### ctx.search(tags, importance=None, age=None, limit=10)
Фильтрация по тегам в RAM dict. Без ML, без векторного поиска.
Пример: ctx.search(["#решение", "#архитектура"], importance="critical")

### ctx.semantic(query, top_k=5, rerank=True) -> list[SessionBrief]
Полный пайплайн: embed(12ms) -> HNSWlib(1.5ms) -> TinyBERT rerank(6ms) -> RAM brief(0.01ms)
Итого ~20ms.

### ctx.anchors(anchor_type=None, session_id=None, limit=20)
```python
# Возвращает:
[{"type": str, "value": str, "session_id": str, "importance": str}]
# Типы: decision/phone/address/person/number/date
# Пример:
ctx.anchors("decision")
# -> [{"type": "decision", "value": "EmbeddingGemma INT8", ...}]
```

### ctx.precision(precision_type=None, importance=None, limit=20)
```python
# Возвращает прецизионные артефакты
[{"type": str, "value": str, "context_tag": str, "session_id": str}]
# Типы: link/concept/quote/formula/data
```

### ctx.full(session_id) -> FullSession [SQLite]
Единственный инструмент который идёт в SQLite. ~0.5ms.
```python
{
    "session_id":    str,
    "tags":          list[str],
    "brief":         str,
    "why_log":       str,
    "content_full":  str,       # полный лог
    "anchors":       list[dict],
    "precision_items": list[dict],
    "created_at":    int,
}
```

### ctx.bridge() -> SessionBridge
Генерирует свежий session bridge для передачи следующему агенту.

---

## 3. Контентная ветка

### content.search(query, project_id=None, status="active", top_k=5)
HNSWlib Content поиск + RAM brief lookup.
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

### content.get(content_id, version=None) -> ContentBlock
version=None возвращает последнюю активную версию. Только метаданные из RAM.

### content.raw(content_id, version=None) -> str [SQLite]
Полный текст контента. lz4 decompress + SQLite. ~2ms.

### content.history(content_id) -> list[VersionSummary]
Все версии включая rejected - без raw текста, только метаданные.

### content.diff(content_id, v1, v2) -> str
Diff между двумя версиями из SQLite.

---

## 4. Управление

| Инструмент | Операция |
|---|---|
| ctx.status() | RAM usage, кол-во сессий, latency stats |
| ctx.evict(n=10) | Принудительно выгрузить N старейших в SQLite |
| ctx.sync() | Принудительный flush pending SQLite операций |
| ctx.load(session_id) | Загрузить архивную сессию из SQLite в RAM |
| ctx.decay() | Принудительный пересчёт age_signal всех сессий |

---

## 5. Паттерны использования агентом

### Паттерн 1: Начало работы
```python
bridge = ctx.active()
# Агент знает: цель, переменные, открытые вопросы
```

### Паттерн 2: Перед написанием кода
```python
related   = ctx.semantic("авторизация JWT токен")
decisions = ctx.anchors("decision")
links     = ctx.precision("link")
```

### Паттерн 3: При обнаружении конфликта
```python
open_c = ctx.search(["#авторизация"], importance="critical")
if open_c:
    full = ctx.full(open_c[0]["session_id"])
```

### Паттерн 4: Поиск архивного контента
```python
archive = content.search("система авторизации", status="all")
if archive:
    history = content.history(archive[0]["content_id"])
    # Изучить почему прошлые версии были отклонены
```

### Паттерн 5: Передача контекста
```python
handoff = ctx.bridge()
# -> system_prompt следующего агента
```
