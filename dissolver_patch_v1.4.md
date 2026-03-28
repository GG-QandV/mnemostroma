# Dissolver — Патч v1.4
## Дата: 2026-03-24 | Добавлено: Content HOT INDEX eviction policy

---

## Content HOT INDEX — Политика вытеснения (WP-17)

### Текущий пробел

Content HOT INDEX растёт неограниченно. Session HOT INDEX имеет скользящее окно (200 сессий). Content требует аналогичной политики ограничения.

### Политика: LRU + recency + active flag

Вытеснение выполняется при доступе (lazy), не по таймеру.

```python
CONTENT_RAM_POLICY = {
    "max_blocks":         500,    # config: content_max_blocks
    "evict_batch":         50,    # вытеснять сразу 50 при превышении
    "hot_protect_hours":   24,    # блоки созданные/изменённые < 24ч → защищены
    "active_protect":    True,    # блоки с status="active" защищены от вытеснения
}
```

### Алгоритм вытеснения

```python
def evict_content_blocks(content_ram: dict, config: dict) -> int:
    """
    Called when len(content_ram) > config["max_blocks"].
    Returns number of evicted blocks.
    """
    now = time.time()
    hot_window = config["hot_protect_hours"] * 3600
    
    candidates = []
    for block_id, data in content_ram.items():
        # Защищённые блоки — пропустить
        if data.get("status") == "active":                     continue
        if (now - data.get("updated_at", 0)) < hot_window:    continue
        if data.get("pinned"):                                 continue
        
        # Score вытеснения: старее + реже используется = приоритет вытеснения
        age_hours = (now - data.get("updated_at", 0)) / 3600
        use_count = data.get("use_count", 0)
        evict_score = age_hours / (1 + use_count)
        candidates.append((evict_score, block_id))
    
    # Вытесняем топ-N с наибольшим evict_score
    candidates.sort(reverse=True)
    evict_count = min(config["evict_batch"], len(candidates))
    
    for _, block_id in candidates[:evict_count]:
        # Данные уже в SQLite (async flush), просто удаляем из RAM
        del content_ram[block_id]
    
    return evict_count
```

### Точки интеграции

| Вызывающий | Условие | Частота |
|------------|---------|---------|
| Conductor event loop | RAM > soft_limit | По событию |
| content.save() | len(content_ram) > max_blocks | При каждом сохранении |
| Consolidation Worker | Плановое обслуживание | Каждые 300 секунд |

> **Важно:** Вытеснение НЕ удаляет данные — контент всегда персистируется в SQLite до вытеснения из RAM.

### Правила защиты

| Условие | Защищён? | Причина |
|---------|----------|---------|
| status = "active" | ДА | В процессе работы |
| updated_at < 24h | ДА | Недавно изменён |
| pinned = True | ДА | Явный пин агента через content.tag() |
| status = "rejected" | НЕТ | Уже заброшен |
| status = "draft", старый | НЕТ | Устаревший черновик |
| status = "archived" | НЕТ | Явно архивирован |

### Формула evict_score

```
evict_score = age_hours / (1 + use_count)
```

- Чем старше блок → тем выше `age_hours` → тем выше приоритет вытеснения
- Чем чаще используется → тем выше `use_count` → тем ниже приоритет вытеснения
- Блок с `age_hours=720` (30 дней) и `use_count=0` → score=720 → вытесняется первым
- Блок с `age_hours=720` и `use_count=71` → score=10 → остаётся дольше

### Изменения конфигурации

Добавить в конфиг диссолвера:

```json
{
  "content_max_blocks": 500,
  "content_evict_batch": 50,
  "content_hot_protect_hours": 24,
  "content_active_protect": true
}
```

---

*Dissolver Patch v1.4 | 2026-03-24 | WP-17*
