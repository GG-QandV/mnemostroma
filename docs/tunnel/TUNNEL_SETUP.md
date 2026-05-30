# Mnemostroma Remote Tunnel Setup Guide

This guide explains how to connect Mnemostroma to web-based AI chats
(Claude.ai, ChatGPT, Perplexity, Grok) using a Cloudflare Tunnel.

---

## Для нетехнических пользователей (For non-technical users)

**Что такое туннель и зачем он мне нужен?**

Обычно Мнемострома работает незаметно на вашем компьютере и общается с программами, которые установлены на этом же компьютере (например, VS Code или Claude Code). Для этого интернет не нужен.

Но с веб-чатами всё иначе. Когда вы открываете сайт Claude.ai или ChatGPT в браузере, сам искусственный интеллект работает на удаленных серверах (в облаке), а не на вашем компьютере. Эти облачные серверы не могут «увидеть» то, что запущено у вас на компьютере под адресом `localhost`. 

**Туннель — это безопасный временный мост.** Он создает специальный публичный интернет-адрес, который указывает прямо на вашу локальную Мнемострому. Облачный ИИ обращается по этому адресу, получает доступ к инструментам памяти, и вы можете пользоваться памятью Мнемостромы прямо в веб-интерфейсе вашего любимого чата!

**Это безопасно?**

- **Полное шифрование:** Все данные между веб-чатом и вашим компьютером надежно шифруются с помощью протокола HTTPS через Cloudflare.
- **Никаких облачных хранилищ:** Ваши разговоры никогда не сохраняются на серверах Cloudflare. Через туннель проходят только запросы к инструментам памяти (например, «какое решение мы приняли на прошлой неделе?»).
- **Полный контроль:** Вы можете в любой момент мгновенно остановить туннель одной командой: `mnemostroma tunnel stop`.
- **Изоляция доступа:** Туннель использует отдельный токен безопасности (`tunnel_token`). Если вы его удалите, никто из интернета не сможет подключиться к вашей Мнемостроме, при этом локальная работа в VS Code никак не пострадает.

---

## Prerequisites (Предварительные требования)

- Установленная и запущенная Мнемострома версии **v2.3.0+** (`mnemostroma on`)
- Установка выполнена с поддержкой SSE (пакет `[sse]` или `[all]`)
- Активное подключение к интернету (для работы Cloudflare)

---

## Quick Setup (Быстрая настройка)

```bash
mnemostroma on             # Запуск демона, если еще не запущен
mnemostroma tunnel start   # Запуск туннеля и OAuth-адаптера
```

При первом запуске Мнемострома автоматически скачает официальный инструмент `cloudflared` (около 35 МБ) в папку `~/.mnemostroma/bin/`.

Вы увидите на экране:

```
  Downloading cloudflared...          ✓
  Starting OAuth adapter :8769...     ✓
  Starting Cloudflare tunnel...       ✓

  ┌──────────────────────────────────────────────────────────┐
  │  Your MCP URL:  https://abc123.trycloudflare.com         │
  │  Bearer token:  cat ~/.mnemostroma/tunnel_token          │
  └──────────────────────────────────────────────────────────┘
```

Просто скопируйте полученный адрес **Your MCP URL** и следуйте инструкциям ниже для вашего чата.

---

## Подключение чатов (Connecting each chat)

### Perplexity (Самый простой вариант — без авторизации)

1. Откройте Perplexity → перейдите в **Settings** (Настройки) → раздел **AI Plugins** или **MCP**.
2. Добавьте новый MCP-сервер:
   - **URL:** вставьте вашу туннельную ссылку (например, `https://abc123.trycloudflare.com`)
   - **Auth:** укажите `None` (Нет)
3. Нажмите **Save** (Сохранить). Готово!

### Claude.ai (Автоматическая авторизация OAuth)

1. Откройте Claude.ai → перейдите в **Settings** (Настройки) → **Integrations** (Интеграции) → **Add Custom Connector** (или сразу откройте ссылку `https://claude.ai/customize/connectors?modal=add-custom-connector`).
2. Заполните поля:
   - **Transport:** выберите `Streamable HTTP`
   - **Name:** напишите `Mnemostroma`
   - **URL:** вставьте туннельный URL с добавлением пути `/mcp` (например, `https://abc123.trycloudflare.com/mcp`)
3. Нажмите **Connect**. Claude.ai автоматически откроет новое окно браузера для подтверждения доступа. Нажмите **Allow Access** (Разрешить доступ).
4. Готово! Теперь Claude.ai имеет доступ к вашей локальной памяти.

### ChatGPT (Автоматическая авторизация OAuth)

1. Откройте ChatGPT → перейдите в **Settings** (Настройки) → **Connectors** (Подключения) → **Add Connector** (Добавить подключение).
2. Заполните поля:
   - **URL:** вставьте вашу туннельную ссылку (например, `https://abc123.trycloudflare.com`)
3. Нажмите **Connect**. Авторизация OAuth произойдет полностью автоматически в браузере.
4. Готово!

### Grok (Подключение по токену Bearer)

1. Откройте Grok → перейдите в **Settings** (Настройки) → раздел **MCP**.
2. Заполните поля:
   - **Server URL:** вставьте вашу туннельную ссылку (например, `https://abc123.trycloudflare.com`)
   - **Bearer token:** введите токен из файла `~/.mnemostroma/tunnel_token`. Узнать его можно командой:
     ```bash
     cat ~/.mnemostroma/tunnel_token
     ```
3. Нажмите **Save** (Сохранить). Готово!

> ⚠️ **Важное примечание:** В бесплатном режиме Cloudflare адрес туннеля меняется при каждом перезапуске команды `mnemostroma tunnel start`. Если вы хотите получить постоянный адрес, ознакомьтесь с разделом [Постоянный адрес туннеля](#permanent-url).

---

## Permanent URL (Постоянный адрес туннеля)

По умолчанию при перезапуске туннеля адрес генерируется случайным образом. Чтобы получить постоянный бесплатный адрес, вам понадобится бесплатный аккаунт Cloudflare:

```bash
# Однократная настройка
~/.mnemostroma/bin/cloudflared tunnel login
~/.mnemostroma/bin/cloudflared tunnel create mnemostroma
# Следуйте инструкциям на экране, чтобы привязать постоянный субдомен
```

После этого вы сможете запускать туннель на своем постоянном адресе, и вам не придется перенастраивать подключения в чатах после перезагрузки.

---

## Autostart (Автозапуск туннеля при старте системы)

Вы можете зарегистрировать туннель как фоновую службу, чтобы он запускался автоматически при старте компьютера:

```bash
mnemostroma service install --component tunnel
```

Служба туннеля будет запускаться в фоне вместе с основным демоном Мнемостромы.

---

## Устранение неполадок (Troubleshooting)

| Проблема (Problem) | Возможная причина (Cause) | Способ решения (Fix) |
|---|---|---|
| Ошибка `cloudflared download failed` | Нет интернета или неподдерживаемая ОС | Проверьте подключение. Установите `cloudflared` вручную (инструкция ниже). |
| Адрес URL не появляется после запуска | `cloudflared` запускается слишком медленно | Подождите 30 секунд. Если не помогло, перезапустите туннель: `mnemostroma tunnel stop && mnemostroma tunnel start`. |
| Claude.ai пишет "Connection failed" | Адрес туннеля изменился после перезапуска | Запустите `mnemostroma tunnel status`, скопируйте новый URL и обновите его в настройках Claude.ai. |
| Ошибка `401 Unauthorized` в Grok | Неверный или пустой токен Bearer | Выполните команду `cat ~/.mnemostroma/tunnel_token`, скопируйте токен полностью и вставьте заново. |
| Не открывается окно OAuth (Claude.ai) | Браузер заблокировал всплывающее окно | Откройте ссылку подтверждения вручную в браузере: `http://localhost:8769/authorize/confirm` |

### Manual cloudflared install (Ручная установка cloudflared)

Если автоматическое скачивание завершилось с ошибкой:
```bash
# Для Linux x64
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 \
  -o ~/.mnemostroma/bin/cloudflared
chmod +x ~/.mnemostroma/bin/cloudflared
```

---

## Developer reference

See [Developer Guide below](#developer-guide) or `src/mnemostroma/integration/tunnel/`.

---

## Developer Guide

### Architecture

```
Web Chat (Claude.ai / ChatGPT / Perplexity / Grok)
        │ HTTPS
        ▼
Cloudflare Tunnel  ←── cloudflared  (~/.mnemostroma/bin/cloudflared)
        │ HTTP localhost:8769
        ▼
mcp_oauth_adapter.py  (Starlette, port 8769)
  ├── /.well-known/oauth-authorization-server   RFC 8414
  ├── /.well-known/oauth-protected-resource     RFC 9728
  ├── /register   DCR
  ├── /authorize  PKCE S256
  ├── /token      code → access_token
  ├── /mcp        HTTP proxy → :8768
  └── /sse        SSE proxy  → :8765
        │
        ├── :8768  mcphttpadapter  (Streamable HTTP — ChatGPT, Claude.ai)
        └── :8765  mcpsseadapter   (SSE — Grok, Perplexity)
                │
                └── Unix socket → Mnemostroma daemon
```

### Key files

| File | Role |
|---|---|
| `src/mnemostroma/integration/mcp_oauth_adapter.py` | Starlette OAuth gateway, port 8769 |
| `src/mnemostroma/integration/tunnel/manager.py` | Tunnel + adapter lifecycle |
| `src/mnemostroma/integration/tunnel/token.py` | `tunnel_token` generation and isolation |
| `src/mnemostroma/integration/tunnel/providers/cloudflare.py` | cloudflared download + process |
| `src/mnemostroma/service_templates/linux/mnemostroma-tunnel.service` | systemd unit |
| `src/mnemostroma/cli/commands.py` | CLI `tunnel start/stop/status` |

### Token isolation

| Token | File | Used by | Scope |
|---|---|---|---|
| `ssetoken` | `~/.mnemostroma/ssetoken` | Claude Desktop, Claude Code, IDE adapters | Local only |
| `tunnel_token` | `~/.mnemostroma/tunnel_token` | Grok Bearer, internal OAuth validation | Internet-facing |

Revoking `tunnel_token` (delete + restart) does not affect local connections.

### OAuth flow (Claude.ai / ChatGPT)

```
Chat server
  1. GET /.well-known/oauth-authorization-server   → metadata (RFC 8414)
  2. POST /register                                → client_id + secret (DCR)
  3. GET /authorize?code_challenge=<S256>          → redirect with ?code=...
     (adapter opens browser tab for user confirmation)
  4. POST /token  code + code_verifier             → access_token (1h TTL)
  5. GET /sse  or  POST /mcp
     Authorization: Bearer <access_token>          → proxy to upstream
```

State is in-memory only (`_clients`, `_codes`, `_tokens` dicts). Restart clears OAuth
state — chats re-authenticate automatically on next connection.

### Adding a new provider

1. Create `src/mnemostroma/integration/tunnel/providers/<name>.py`
   with `ensure_<name>()` and `start_tunnel(port)` async functions
   matching the `cloudflare.py` interface
2. Add to `manager.py` provider dispatch:
   ```python
   if provider == "cloudflare":
       tunnel_proc, url = await start_tunnel(port=ADAPTER_PORT)
   elif provider == "your_provider":
       tunnel_proc, url = await your_provider.start_tunnel(port=ADAPTER_PORT)
   ```
3. Add CLI `--provider` option in `commands.py`

### Running tests

```bash
# New tunnel tests only
pytest tests/test_tunnel_token.py \
       tests/test_mcp_oauth_adapter.py \
       tests/test_tunnel_manager.py -v

# Full suite with regression check
pytest tests/ -v --tb=short

# Fast mode
pytest tests/ \
  --ignore=tests/test_memory_layers.py \
  --ignore=tests/test_data_contracts.py -v
```

Expected: **609+ passed, 0 failed**.
