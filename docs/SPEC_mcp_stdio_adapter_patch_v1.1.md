# Spec: mcp_stdio_adapter Patch v1.1

> Status: Draft | Date: 2026-04-10
> Phase: 12.B
> Depends on: proxy_passthrough.py (Spec 12.A — читает current_session)

---

## 1. Overview

`mcp_stdio_adapter.py` при старте записывает `session_id` текущей сессии в `~/.mnemostroma/current_session`. Файл читает `proxy_passthrough.py` чтобы привязать перехваченный трафик Claude Code к правильной Mnemostroma-сессии.

---

## 2. Контракт файла

```
Путь:    ~/.mnemostroma/current_session
Формат:  одна строка, plain UTF-8, без trailing newline
Пример:  2026-04-10-mcp-a3f2b1
Пишет:   mcp_stdio_adapter при старте (один раз)
Читает:  proxy_passthrough.py при каждом запросе
```

Файл не удаляется при завершении адаптера. Proxy использует последний известный `session_id` до следующего перезапуска адаптера.

---

## 3. Дельта кода

**Файл:** `src/mnemostroma/integration/mcp_stdio_adapter.py`

```python
# Добавить константу рядом с _MNEMO_DIR:
_CURRENT_SESSION_FILE = _MNEMO_DIR / "current_session"

# Добавить в main(), между stdio_server() и app.run():
async def main() -> None:
    # ... существующий код без изменений ...
    async with stdio_server() as (read_stream, write_stream):

        # NEW: зафиксировать session_id для proxy_passthrough
        try:
            result = await _ipc_call("ctx_active", {})
            sid = (result or {}).get("session_id") or f"passthrough-{date.today().isoformat()}"
        except Exception:
            sid = f"passthrough-{date.today().isoformat()}"
        _CURRENT_SESSION_FILE.write_text(sid, encoding="utf-8")
        # END NEW

        await app.run(read_stream, write_stream, app.create_initialization_options())
```

Добавляемый импорт:

```python
from datetime import date   # если ещё не импортирован
```

**Итого: +1 константа, +6 строк в main(), +1 импорт.**

---

## 4. Поведение при недоступном daemon

`_ipc_call("ctx_active", {})` бросит `ConnectionError` если daemon не запущен. `except Exception` поглощает его — адаптер продолжает работу с fallback session_id вида `passthrough-2026-04-10`.

Proxy при этом всё равно наблюдает трафик — сессия будет анонимной, но не потеряется.

---

## 5. Тесты

- `test_current_session_written_on_start()` — `main()` записывает файл до `app.run()`
- `test_current_session_fallback_on_daemon_down()` — daemon недоступен → файл содержит `passthrough-{date}`
- `test_current_session_uses_ctx_active_id()` — daemon возвращает `session_id` → файл содержит его
