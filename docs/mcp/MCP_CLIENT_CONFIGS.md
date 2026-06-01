# MCP Client Configs — Mnemostroma

Актуальное состояние подключения всех CLI/IDE клиентов к Mnemostroma.
Токен хранится в `~/.mnemostroma/sse_token` — единый для SSE и HTTP.

## Порты

| Транспорт | Порт | Эндпоинт | Примечание |
|-----------|------|----------|------------|
| Streamable HTTP | 8768 | `/mcp` | Основной, embedded в daemon |
| SSE | 8765 | `/sse` | Embedded в daemon |

---

## Antigravity (основной профиль)

**Конфиг:** `~/.gemini/config/mcp_config.json` (симлинк ← `~/.gemini/antigravity/mcp_config.json`)
**Транспорт:** Streamable HTTP

```json
"mnemostroma": {
  "serverUrl": "http://127.0.0.1:8768/mcp",
  "headers": {
    "Authorization": "Bearer <TOKEN>"
  },
  "disabledTools": ["ctx_get", "content_get"]
}
```

---

## Antigravity IDE

**Конфиг:** `~/.gemini/antigravity-ide/mcp_config.json`
**Транспорт:** Streamable HTTP

```json
"mnemostroma": {
  "serverUrl": "http://127.0.0.1:8768/mcp",
  "headers": {
    "Authorization": "Bearer <TOKEN>"
  },
  "disabledTools": ["ctx_get", "content_get"]
}
```

---

## VS Code

**Конфиг:** `~/.config/Code/User/mcp.json`
**Транспорт:** Streamable HTTP

```json
"mnemostroma": {
  "type": "http",
  "url": "http://127.0.0.1:8768/mcp",
  "headers": {
    "Authorization": "Bearer <TOKEN>"
  }
}
```

---

## Cursor

**Конфиг:** `~/.cursor/mcp.json`
**Транспорт:** SSE

```json
"mnemostroma": {
  "type": "sse",
  "url": "http://127.0.0.1:8765/sse?token=<TOKEN>"
}
```

---

## Claude Code

**Конфиг:** `~/.claude/mcp.json`
**Транспорт:** SSE

```json
"mnemostroma": {
  "type": "sse",
  "url": "http://127.0.0.1:8765/sse?token=<TOKEN>"
}
```

---

## OpenCode

**Конфиги:** `~/.opencode/opencode.json` и `~/.config/opencode/opencode.json`
**Транспорт:** Streamable HTTP (`type: "remote"`)

```json
"mnemostroma": {
  "type": "remote",
  "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>",
  "enabled": true
}
```

> Примечание: OpenCode использует `type: "remote"` = Streamable HTTP. Порт 8765/SSE вызывает ошибку аутентификации.

---

## Qoder

**Конфиг:** `~/.qoder/mcp.json`
**Транспорт:** Streamable HTTP

```json
"mnemostroma": {
  "serverUrl": "http://127.0.0.1:8768/mcp",
  "headers": {
    "Authorization": "Bearer <TOKEN>"
  }
}
```

---

## Workspace (Project_mnemostroma)

**Конфиг:** `Project_mnemostroma/.mcp.json`
**Транспорт:** Streamable HTTP

```json
"mnemostroma": {
  "serverUrl": "http://127.0.0.1:8768/mcp",
  "headers": {
    "Authorization": "Bearer <TOKEN>"
  }
}
```

---

## Получить токен

```bash
cat ~/.mnemostroma/sse_token
```
