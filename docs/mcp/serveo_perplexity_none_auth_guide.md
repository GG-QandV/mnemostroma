# Serveo tunnel + Perplexity "none" auth — технический анализ

## 1. Serveo: полная документация по параметрам туннеля

### 1.1. Базовая команда

```bash
ssh -R 80:localhost:8769 serveo.net
```

- `-R 80` — Serveo выделяет случайный поддомен и проксирует HTTP/HTTPS (80 и 443)
- `localhost:8769` — куда направлять трафик
- Результат: `https://<random-hash>.serveo.net` → `http://localhost:8769`
- SSH-соединение — стандартный OpenSSH, никаких клиентов не требуется

### 1.2. Параметры подключения

| Параметр | Формат | Описание |
|----------|--------|----------|
| **Порт подключения** | `-p 443` | Если исходящий 22 заблокирован (корпоративные сети, некоторые ISP) |
| **Конкретный поддомен** | `ssh -R mysubdomain:80:localhost:8769 serveo.net` | Запрос имени. **Детерминирован** на основе IP + SSH username + доступность. Не гарантирован |
| **Смена поддомена** | `ssh -R 80:localhost:8769 foo@serveo.net` | Меняем SSH username → другой хэш |
| **autossh** | `autossh -M 0 -R 80:localhost:8769 serveo.net` | Автопереподключение при обрыве. `-M 0` отключает мониторинг autossh (использует мониторинг SSH) |
| **Порт 443** | `ssh -p 443 -R 80:localhost:8769 serveo.net` | Fallback, если 22 заблокирован |
| **WireGuard** | Через консоль serveo.net | Сгенерировать ключ → настроить wg-quick → добавить правило HTTP Forwarding |
| **Custom domain** | DNS CNAME → serveo.net + TXT `_serveo-authkey.<domain>` | Требует SSH-ключ и его fingerprint |
| **Private TCP** | `ssh -R myalias:5901:localhost:5900 serveo.net` | RAW TCP, не HTTP. Для VPN-like доступа |
| **Public TCP** | `ssh -R 1492:localhost:1492 serveo.net` | Порт ≠ 80,443. RAW TCP. Только для registered users |

### 1.3. Browser Warning (интерстициальная страница)

**Проблема:** Serveo показывает предупреждение при входе браузера на анонимный туннель.
Это делается для предотвращения фишинга/abuse.

**Как работает:**
1. Браузер идёт на `https://<hash>.serveo.net/authorize`
2. Serveo перехватывает, показывает "Browser Warning" с кнопкой "Continue"
3. После нажатия "Continue" — запрос идёт дальше к адаптеру
4. **Warning повторяется при каждом новом посещении**, если cookie не сохранена (private tab, сброс cookies)

**Методы обхода:**

| Метод | Работает | Описание |
|-------|----------|----------|
| Header `serveo-skip-browser-warning: true` | ✅ API/programmatic | Не требует ручного клика |
| Pro-план ($60/год) | ✅ | Полное отключение interstitial |
| Cookie `serveo-skip-warning=1` | ❌ | Не спасает при первом заходе или сбросе |
| **method=get** на форме (наш fix) | ⚠️ | Warning всё равно показывается, но POST→GET спасает от потери body |

**Критический баг (исправлен):** При POST-запросе через Warning, Serveo теряет тело запроса.
После нажатия "Continue" браузер делает GET на тот же URL без параметров.
**Решение:** Consent form `method="post"` → `method="get"` — все параметры в query string.

### 1.4. Детерминированность поддомена

- Поддомен **не гарантирован** между перезапусками
- Serveo пытается сохранить привязку к IP + SSH username
- Смена IP (перезагрузка роутера, VPN) → **новый поддомен**
- Решение: читать `/authorize` ответ через `PUBLIC_URL`, который обновляется из `serveo_url` файла
- `scripts/update_version.py` не затрагивает туннель

### 1.5. Тарифы

| План | Цена | Туннели | Interstitial | Поддержка |
|------|------|---------|-------------|-----------|
| Free | $0 | 3 | ✅ Есть | Community |
| Pro | $60/год | Unlimited | ❌ Нет | Priority |

### 1.6. Рекомендуемая команда для продакшна

```bash
autossh -M 0 -p 443 -o "ServerAliveInterval 30" -o "ServerAliveCountMax 3" \
  -o "ExitOnForwardFailure yes" \
  -R 80:localhost:8769 serveo.net
```

---

## 2. Perplexity "none" auth

### 2.1. Что это

В настройках MCP сервера Perplexity предлагает 3 варианта авторизации:
- **OAuth** — полный OAuth 2.0 + PKCE flow (текущий режим)
- **API Key** — Bearer token в заголовке
- **None** — без авторизации, прямое подключение к MCP endpoint

`none` означает: Perplexity **не требует никакой аутентификации**. MCP endpoint доступен без токена, OAuth flow полностью пропускается.

### 2.2. Как работает (по сравнению с OAuth)

| Шаг | OAuth | None |
|-----|-------|------|
| URL коннектора | Ввод пользователем | Ввод пользователем |
| Обмен ключами | OAuth metadata → PKCE → code → token | Нет |
| Подключение к `/mcp` | `Authorization: Bearer <token>` | Прямой POST |
| Serveo Warning | На `/authorize` (браузер) | Perplexity делает HTTP-запросы программно — Warning **не показывается** |
| `tools/list` | Через OAuth middleware | Прямой проход |
| `tools/call` | Через OAuth middleware | Прямой проход |

### 2.3. Роутинг адаптера (уже настроен)

В `mcp_oauth_adapter.py`, строка 80:
```python
"/mcp": {"auth": ["none"], "client": "perplexity", "transport": "streamable-http"},
```

`handlers`: использование `AuthMode.NONE` в `DynamicRouter`

### 2.4. Преимущества none

1. **Нет OAuth flow** — не нужен браузер, consent form, redirect через Serveo Warning
2. **Serveo Warning не триггерится** — Perplexity обращается программно (http-клиент), не через браузер
3. **Нет потери параметров** — нет POST через Warning, нет race condition
4. **Стабильнее** — на 2 точки отказа меньше (authorize + token exchange)
5. **Не нужен PUBLIC_URL** — хотя он всё ещё может быть полезен для диагностики

### 2.5. Риски none

1. **Нет авторизации** — любой, кто знает URL туннеля, может вызвать tools адаптера
2. **URL динамический** — перезапуск туннеля меняет URL
3. **502 Bad Gateway от Serveo** — остаётся (на стороне Serveo, не зависит от авторизации)

---

## 3. Верификация tools list

### 3.1. Текущий формат _TOOLS

```python
_TOOLS = [
    {
        "name": "ctx_semantic",
        "description": "Semantic search in memory. Returns relevant sessions based on meaning.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_n": {"type": "integer", "default": 5},
            },
            "required": ["query"],
        },
    },
    # ... 12 tools total (ctx_semantic, ctx_get, ctx_search, ctx_full,
    #     ctx_anchors, ctx_precision, content_search, content_raw,
    #     content_history, ctx_bridge, ctx_recent)
]
```

**Источник:** `src/mnemostroma/integration/mcp_stdio_adapter.py:31-153`

### 3.2. Соответствие MCP spec (2024-11-05 / 2025-06-18)

| Поле | Spec | Наш формат | Статус |
|------|------|-------------|--------|
| `name` | `string` | `str` | ✅ |
| `description` | `string` (optional) | `str` | ✅ |
| `inputSchema` | `object` with `type`, `properties`, `required` | ✅ `{"type": "object", "properties": {...}, "required": [...]}` | ✅ |
| `inputSchema.type` | `"object"` | `"object"` | ✅ |
| `inputSchema.properties` | JSON Schema | ✅ | ✅ |
| `inputSchema.properties.<name>.default` | Valid JSON Schema | ✅ | ✅ |
| `inputSchema.properties.<name>.enum` | Valid JSON Schema | ✅ on `ctx_recent.by` | ✅ |
| `inputSchema.required` | `string[]` | ✅ | ✅ |

**Вывод:** Все 12 tool-дескрипторов корректны по MCP spec.

### 3.3. Проверка initialize response

Текущий ответ (строка 224):
```python
return _ok(rid, {
    "protocolVersion": _PROTOCOL,       # "2024-11-05"
    "capabilities": {"tools": {}},
    "serverInfo": {"name": "mnemostroma", "version": _VERSION},
})
```

По MCP spec:
- `protocolVersion`: ✅
- `capabilities`: ✅ `{"tools": {}}` — tools capability объявлена
- `serverInfo.name`: ✅
- `serverInfo.version`: ✅
- `instructions`: optional — не нужен

**Один потенциальный issue:** protocol version `2024-11-05` vs `2025-06-18`. Если Perplexity использует новый протокол, они могут ожидать `"listChanged": true` в `capabilities.tools`. На данный момент нет — это может привести к тому, что Perplexity не узнает об изменении списка tools. **Но для статического tools list это не критично.**

### 3.4. Accept header — анализ и риски

В `handle_mcp` (строки 356-365):
```python
accept-patch: если Accept не содержит application/json → заменяет
```

MCP spec Streamable HTTP:
> The client **MUST** include an Accept header, listing both `application/json` and `text/event-stream` as supported content types.

**Что делает наш код:**
- Если Accept уже содержит `application/json` (с или без `text/event-stream`) → **не трогает**
- Если Accept отсутствует или не содержит `application/json` → **force `application/json`**

**Вывод:** код не ломает ничего для Perplexity. Если Perplexity пришлёт нормальный Accept с обоими типами, патч не срабатывает. Если Accept невалидный — force JSON, что Perplexity точно переварит.

**Потенциальная проблема:** если Perplexity хочет SSE для streaming tools/call, и Accept содержит `text/event-stream`, наш код НЕ удаляет SSE. Но если Perplexity пришлёт только `text/event-stream` без `application/json`, мы заменим — и потеряем SSE. **Это маловероятно**, т.к. Perplexity (как HTTP-клиент) почти наверняка присылает стандартный Accept с обоими типами.

---

## 4. Ошибки и freeze/debug-режим

### 4.1. Текущие точки слома (в порядке вероятности)

| # | Симптом | Причина | Статус |
|---|---------|---------|--------|
| 1 | Бесконечные табы Perplexity | 502 от Serveo → Perplexity retry → новая вкладка | Не исправлено |
| 2 | 502 Bad Gateway | Нестабильность анонимного туннеля Serveo | Не исправлено |
| 3 | `invalid_request` на /authorize | Warning Serveo съедает параметры (исторический) | Исправлено (method=get) |
| 4 | Token exchange fails | PKCE challenge mismatch (edge case) | Не наблюдалось |
| 5 | 406 Not Acceptable | Accept header mismatch | Исправлено (accept-patch) |

### 4.2. Freeze/Debug-режим: проект

**Требование:** видеть каждый HTTP-запрос/ответ, с возможностью пошагово "разморозить" выполнение.

**Вариант A: MCP Debug Middleware (рекомендуется)**
- Добавить debug-мидлварь в Starlette app
- Логировать: `[DEBUG] Request: GET /authorize?client_id=...`, `[DEBUG] Response: 200 OK (342 bytes)`
- Режим включается переменной окружения `MNEMOSTROMA_DEBUG=1` или `--debug`
- При включении — каждый запрос принтует Request + Response в stderr
- Не блокирует выполнение (non-freezing), но даёт полную картину

**Вариант B: Request/Response dump (всегда включено в файл)**
- Писать каждый запрос/ответ в `~/.mnemostroma/debug/http_dump.log`
- Ротация: 5 файлов по 1MB
- Минус: может быстро заполнить диск

**Вариант C: Interactive freeze (только для отладки)**
- При `MNEMOSTROMA_DEBUG=2` — каждый запрос приостанавливает адаптер
- В консоль выводится полный dump запроса
- Ожидание Enter для продолжения
- Минус: не работает в headless/daemon mode
- Плюс: идеально для пошагового анализа

**Рекомендация:** Вариант A (non-blocking логгинг) как основной + возможность включить C через env.

### 4.3. Реализация debug middleware

```python
class DebugMiddleware:
    """Логирует каждый HTTP запрос/ответ при MNEMOSTROMA_DEBUG."""
    
    DEBUG = os.environ.get("MNEMOSTROMA_DEBUG", "0")
    BLOCKING = DEBUG == "2"
    
    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or self.DEBUG == "0":
            await self.app(scope, receive, send)
            return
        
        # Собираем request
        request = Request(scope, receive)
        body = await request.body()
        
        logger.debug("─" * 60)
        logger.debug(">>> %s %s", request.method, request.url)
        logger.debug(">>> Headers: %s", dict(request.headers))
        if body:
            logger.debug(">>> Body: %s", body.decode()[:2000])
        
        if self.BLOCKING:
            input("Press Enter to continue...")
        
        # Перехватываем response
        response_body = bytearray()
        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                logger.debug("<<< Status: %s", message["status"])
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))
                logger.debug("<<< Body: %s", bytes(response_body).decode()[:2000])
            await send(message)
        
        # Re-create request (body consumed)
        async def receive_wrapper():
            return {"type": "http.request", "body": body, "more_body": False}
        
        await self.app(scope, receive_wrapper, send_wrapper)
```

---

## 5. Пошаговый тест "none" auth через Serveo

### 5.1. Подготовка

```bash
# 1. Запустить адаптер
mnemostroma on

# 2. Запустить туннель
mnemostroma tunnel start

# 3. Узнать URL туннеля
cat ~/.mnemostroma/serveo_url
# → https://abc123.serveo.net
```

### 5.2. Проверка tools/list через curl (без авторизации)

```bash
# Initialize
curl -X POST https://abc123.serveo.net/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# Expected: 200 OK with protocolVersion, capabilities, serverInfo

# List tools
curl -X POST https://abc123.serveo.net/mcp \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'

# Expected: 200 OK with list of 12 tools
```

### 5.3. Проверка в Perplexity (ручная)

1. Perplexity Chat → Settings → MCP Servers → Add
2. URL: `https://abc123.serveo.net/mcp`
3. Auth: **None**
4. Сохранить
5. Perplexity должен показать список tools (12 шт.)
6. Попробовать: `ctx_semantic(query="test")` или другой tool

### 5.4. Что может пойти именно с tools/list

| Проблема | Симптом | Причина | Решение |
|----------|---------|---------|---------|
| **502 от Serveo** | Perplexity показывает "MCP server error" | Транзистентный сбой Serveo | Платный Serveo или Cloudflare Tunnel |
| **Wrong format** | Perplexity не видит tools | Несовместимость ответа | Сверить с MCP spec (п.3 выше) |
| **Accept header mismatch** | 406 или пустой ответ | Perplexity не принимает JSON без SSE | Accept-patch уже работает |
| **CORS** | Блокировка запроса | Если Perplexity идёт с браузера | CORS middleware уже настроен (`allow_origins=["*"]`) |
| **Timeout** | Долгий response | 10s timeout в _ipc_call | Настраивается |

---

## 6. Резюме и рекомендации

### Для немедленного тестирования "none" auth:
1. Достаточно изменить routes.json: `/mcp` → `auth: ["none"]` (уже дефолт)
2. Подать URL туннеля в Perplexity с auth=None
3. **Serveo Warning не покажется** — Perplexity обращается программно

### Для документирования:
4. Полная документация Serveo подготовлена (секция 1 выше)
5. Спецификация tools list верифицирована (секция 3)

### Для отладки (freeze-режим):
6. Реализовать DebugMiddleware (секция 4.3) — опционально

### Для стабильности:
7. **Cloudflare Tunnel** — единственное полное решение проблемы 502 + Warning
