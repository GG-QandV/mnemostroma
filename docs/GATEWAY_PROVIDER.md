# Gateway Provider Dispatch — Safe Deployment Guide

> **Область:** R6b–R14 | **Статус:** BETA | **Ветки:** `feat/gateway-r*`

---

## Минимальная конфигурация

```json
{
  "gateway": {
    "provider_mode": "configured",
    "provider_base_url": "https://provider.example/v1",
    "provider_token_env": "MNEMO_PROVIDER_TOKEN",
    "provider_timeout_seconds": 30,
    "dispatch_mode": "http",
    "memory_mode": "off",
    "observation_mode": "off",
    "max_concurrent_dispatches": 8,
    "max_concurrent_memory_requests": 2
  }
}
```

### Safe defaults

Gateway поставляется с безопасными значениями по умолчанию — включение
требует явного изменения:

| Поле | Default | Безопасное значение |
|------|---------|---------------------|
| `enabled` | `false` | `false` |
| `provider_mode` | `disabled` | `configured` для dispatch |
| `dispatch_mode` | `dry_run` | `dry_run` → `fake` → `http` |
| `memory_mode` | `off` | `off` |
| `observation_mode` | — | `off` |

---

## Токен провайдера

Токен **никогда** не должен храниться в JSON, command line, логах или
клиентском запросе. Единственный способ — переменная окружения:

```bash
export MNEMO_PROVIDER_TOKEN="sk-your-provider-key-here"
```

`provider_token_env` содержит **имя переменной**, а не сам токен.
Gateway читает токен при каждом dispatch-запросе. Если переменная
пуста или не установлена — возвращается `503 provider_credentials_unavailable`,
сетевой вызов не производится.

---

## Loopback-разработка (localhost)

Для тестирования без внешнего провайдера:

```json
{
  "gateway": {
    "provider_mode": "configured",
    "provider_base_url": "http://127.0.0.1:8781",
    "provider_token_env": "MNEMO_PROVIDER_TOKEN",
    "dispatch_mode": "http"
  }
}
```

HTTP разрешён только для loopback-адресов (`127.0.0.1`, `::1`,
`localhost`). Для любых других хостов требуется HTTPS.

---

## Production-конфигурация

```json
{
  "gateway": {
    "enabled": true,
    "provider_mode": "configured",
    "provider_base_url": "https://api.openai.com/v1",
    "provider_token_env": "MNEMO_PROVIDER_TOKEN",
    "dispatch_mode": "http",
    "memory_mode": "off",
    "observation_mode": "off",
    "max_concurrent_dispatches": 4
  }
}
```

**Важно:** Gateway всегда POSTит в `{provider_base_url}/chat/completions`.
Если `provider_base_url` = `https://api.openai.com/v1`, то URL запроса
будет `https://api.openai.com/v1/chat/completions`.

---

## Проверка через curl

```bash
curl -X POST http://127.0.0.1:8780/v1/chat/completions \
  -H "Authorization: Bearer $(cat /run/secrets/gateway-token)" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello"}]
  }'
```

Поле `stream` опущено или `false`. `stream: true` возвращает
`400 invalid_request`.

---

## Ожидаемый нормализованный ответ

```json
{
  "id": "chatcmpl_mnemo_abc123...",
  "object": "chat.completion",
  "created": 1783720000,
  "model": "gpt-4",
  "choices": [
    {
      "index": 0,
      "message": {
        "role": "assistant",
        "content": "Hello! How can I help you?"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens": 10,
    "completion_tokens": 5,
    "total_tokens": 15
  }
}
```

Gateway генерирует собственный `id` (префикс `chatcmpl_mnemo_`),
`created` — UNIX timestamp момента нормализации, `model` — модель из
запроса клиента (не из ответа upstream).

---

## Коды ошибок

| HTTP | Code | Причина |
|------|------|---------|
| 400 | `invalid_request` | Некорректное тело запроса |
| 400 | `invalid_json` | Невалидный JSON |
| 401 | `unauthorized` | Отсутствует или неверен Bearer-токен |
| 502 | `provider_invalid_response` | Провайдер вернул некорректный ответ |
| 502 | `provider_auth_failed` | Провайдер отклонил токен (401/403) |
| 502 | `provider_unreachable` | Не удалось соединиться с провайдером |
| 503 | `provider_credentials_unavailable` | Токен провайдера не установлен |
| 503 | `provider_rate_limited` | Провайдер вернул 429 |
| 503 | `memory_unavailable` | Ошибка memory injection |
| 503 | `provider_busy` | Достигнут лимит concurrent dispatch |
| 504 | `provider_timeout` | Провайдер не ответил за timeout |

Ни один ответ не содержит: URL провайдера, имя переменной токена,
Bearer-токен, raw тело upstream, содержимое memory injection или
конфиденциальные данные.

---

## Memory injection (R7)

```json
{
  "gateway": {
    "memory_mode": "active",
    "memory_max_tokens": 600
  }
}
```

- Memory-контекст добавляется как отдельное system-сообщение **после**
  существующих system-сообщений, перед первым non-system сообщением.
- Исходный prompt клиента не мутируется.
- Memory-контекст **не возвращается** в ответе клиенту.
- Без подключённого `ConductorProxy` (через `create_gateway_app`)
  `memory_mode=active` возвращает `503 memory_unavailable` до вызова
  провайдера.
- `memory_mode=off` и `planned` не вызывают injector.

---

## Observation (R8–R9)

```json
{
  "gateway": {
    "observation_mode": "active"
  }
}
```

- Записывает только финальную пару user/assistant строк **после**
  успешного completion.
- Best-effort: ошибка observation не меняет ответ клиенту.
- 2-секундный timeout, task отслеживается в `ObservationTaskRegistry`.
- На shutdown приложение дожидается завершения observation-задач (3s).
- Без `ConductorProxy` observation не планируется.
- `observation_mode=off` — по умолчанию, не создаёт задачи.

---

## Safe rollback

При проблемах — вернуть `dispatch_mode` в `dry_run` или
`provider_mode` в `disabled`:

```json
{
  "gateway": {
    "provider_mode": "disabled",
    "dispatch_mode": "dry_run"
  }
}
```

В `dry_run` Gateway возвращает route-plan без вызова провайдера,
memory injection или observation.

---

## Non-goals (R15)

- Streaming (`stream: true` → `400 invalid_request`)
- Tools, functions, tool_choice, response_format
- Retries, circuit breaker, fallback между провайдерами
- Rate limiting по IP/user
- Shared `httpx.AsyncClient` (scoped per request)
- Provider-sidecar или публичный Gateway-port
- Durable outbox для observation
- Замена существующих MCP/proxy/tunnel адаптеров
