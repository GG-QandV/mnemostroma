# Agent Integration — Спецификация
## Mnemostroma | v2.0 | 2026-03-25

> Conductor = proxy между юзером и LLM.
> Контекст памяти гарантирован на архитектурном уровне.
> Агент не «загружает память» — он всегда её видит.

---

## 1. Принцип: Conductor Proxy

Conductor оборачивает каждый вызов LLM. Не injection, не tool-first —
**middleware** который гарантирует наличие контекста.

```
User message
     │
     ▼
CONDUCTOR (proxy)
     │
     ├── [1] ctx.active() → собрать контекст (~1ms RAM)
     ├── [2] ctx.semantic(user_message) → relevant past (~20ms)
     ├── [3] Собрать prompt = base + <memory_context> + tools
     ├── [4] → LLM (system=prompt, messages=history, tools=mcp_tools)
     ├── [5] ← LLM response (+ возможные tool_calls)
     ├── [6] Observer.process(user_message + response + tool_calls)
     └── [7] → User получает ответ

Агент НЕ решает загружать ли память.
Conductor ВСЕГДА подставляет контекст.
Это не опция — это архитектура.
```

**Одна архитектура для всех классов моделей.** Нет отдельных стратегий для A/B/C — proxy работает с любым LLM.

---

## 2. Prompt Template

Conductor собирает prompt при **каждом вызове LLM**:

```
PROMPT = BASE_SYSTEM_PROMPT
       + MEMORY_CONTEXT_BLOCK
       + MEMORY_TOOLS_INSTRUCTION (если модель поддерживает tools)
```

### 2.1 Memory Context Block (всегда, все модели)

```xml
<memory_context updated="2026-03-25T14:32:00Z">

<decisions>
- Session tokens вместо JWT (вчера, critical)
- PostgreSQL для основной БД (3 дня назад, critical)
- REST API, не GraphQL (5 дней назад, important)
</decisions>

<principles>
- НИКОГДА: токены в localStorage
- ВСЕГДА: E2E encryption для user data
</principles>

<conflicts>
- Auth: JWT (session_012) отменён, заменён session tokens (session_018)
</conflicts>

<deadlines>
- Deploy v1.0: пятница 28 марта (через 3 дня)
</deadlines>

<last_session>
Middleware авторизации. Выбрали passport.js. Открыто: refresh token flow.
</last_session>

<relevant>
- session_015: token rotation, sliding window, 7 дней expiry
- session_008: обсуждали JWT refresh — ДО перехода на session tokens
</relevant>

</memory_context>
```

`<relevant>` — динамическая секция, ctx.semantic(user_message) при каждом вызове.
Остальное — кэшируется, пересчитывается при значимом изменении.

### 2.2 Memory Tools Instruction (только если модель поддерживает tools)

```
You have memory tools for deeper search when the context above isn't enough:
- ctx_semantic(query) — search by meaning
- ctx_anchors(type) — find exact facts (phones, URLs, decisions)
- ctx_precision(type) — find verbatim artifacts (formulas, quotes, links)
- ctx_full(session_id) — full session transcript
- content_search(query) — find code/chapters from past projects
You don't need to save anything — memory is recorded automatically.
```

Для моделей без tool use — эта секция не добавляется. Контекст из memory_context достаточен.

---

## 3. Адаптация по классу модели

Не отдельные стратегии — **один proxy, разная детализация:**

| Класс | Модели | memory_context | Tools | Tokens |
|-------|--------|---------------|-------|--------|
| A (большие) | Claude, GPT-4o | Полный (6 секций) | ✅ 9 tools | ~400-600 |
| B (средние) | Llama 70B, Mistral | Полный | ✅ 5 tools (упрощённые descriptions) | ~400-600 |
| C (малые Q4) | Phi-3, Gemma 2B | Сокращённый (3 секции: decisions + principles + relevant) | ❌ нет tools | ~150-250 |
| C-mini (2-4K контекст) | TinyLlama, Gemma 2B | Минимальный (principles + 1 relevant) | ❌ нет tools | ~80-120 |

```json
{
  "integration": {
    "strategy": "auto",
    "model_class": null,
    "context_budget_tokens": 600,
    "context_budget_min_tokens": 80,
    "tools_enabled": true,
    "tools_descriptions": "full",
    "relevant_context_top_n": 3,
    "decisions_top_n": 7,
    "cache_static_every_n_messages": 5
  }
}
```

Auto-detection:
```python
def detect_model_class(model_name: str, context_window: int, 
                       tool_use: bool) -> str:
    if tool_use and context_window >= 32000:
        return "A"
    if tool_use and context_window >= 8000:
        return "B"
    if context_window >= 4000:
        return "C"
    return "C-mini"
```

---

## 4. Кэширование

Не пересчитывать всё при каждом сообщении:

```
Статическая часть (decisions, principles, conflicts, deadlines):
  → кэшировать
  → пересчитывать каждые N сообщений ИЛИ при триггере:
    - новый conflict_flag
    - новый principle
    - дедлайн истёк/появился
    - decisions top-N drift > 30%

Динамическая часть (relevant):
  → ctx.semantic(user_message) при каждом вызове (~20ms)
  → результат НЕ кэшируется (зависит от текущего сообщения)

Итого overhead на каждое сообщение:
  Кэш попал:  ~20ms (только semantic search для relevant)
  Кэш промах: ~25ms (semantic + пересборка static)
```

---

## 5. Observer — полный охват I/O

Observer слушает ВСЁ через Conductor proxy:

| Канал | Что ловит | Feedback |
|-------|----------|----------|
| User message | Сущности, решения, принципы | — |
| Assistant response | Сущности, результаты | — |
| Tool calls (ctx_semantic и др.) | Какие запросы к памяти | USE signal |
| Tool results | Что вернула память | USE/IGNORE (использовал ли агент результат) |

**Нет провала #5** (Observer не видит tool calls) — Conductor proxy видит всё.

---

## 6. Tool Descriptions

```json
{
  "tools": [
    {
      "name": "ctx_semantic",
      "description": "Search memory by meaning. Use when memory_context doesn't have enough detail on a topic. Returns relevant past sessions.",
      "parameters": {
        "query": {"type": "string", "description": "Topic to remember"},
        "top_n": {"type": "integer", "default": 5}
      }
    },
    {
      "name": "ctx_anchors",
      "description": "Find exact facts: phone numbers, URLs, decisions, dates. Use when you need a precise value.",
      "parameters": {
        "type": {"type": "string", "enum": ["decision","phone","address","person","number","date","link"]},
        "query": {"type": "string"}
      }
    },
    {
      "name": "ctx_precision",
      "description": "Find verbatim artifacts: links, formulas, quotes, code snippets stored exactly as recorded.",
      "parameters": {
        "type": {"type": "string", "enum": ["link","concept","quote","formula","data"]},
        "query": {"type": "string"}
      }
    },
    {
      "name": "ctx_full",
      "description": "Get complete session transcript. Use only when you need exact wording — this is expensive.",
      "parameters": {
        "session_id": {"type": "string"}
      }
    },
    {
      "name": "ctx_principles",
      "description": "List all permanent rules. These must NEVER be violated.",
      "parameters": {}
    },
    {
      "name": "ctx_urgent",
      "description": "List active deadlines and urgent items.",
      "parameters": {}
    },
    {
      "name": "content_search",
      "description": "Search past code, chapters, configs with version history.",
      "parameters": {
        "query": {"type": "string"},
        "content_type": {"type": "string", "enum": ["function","class","chapter","scene","config"]}
      }
    },
    {
      "name": "ctx_get",
      "description": "Get details of a specific session by ID. Use when memory_context references a session you need more info about.",
      "parameters": {
        "session_id": {"type": "string"}
      }
    },
    {
      "name": "ctx_search",
      "description": "Search memory by tags. Faster than semantic but requires exact tag match.",
      "parameters": {
        "tags": {"type": "array", "items": {"type": "string"}}
      }
    }
  ]
}
```

---

## 7. Жизненный цикл сообщения

```
[1] User message → Conductor

[2] Conductor:
    static_cache valid?
      YES → use cache (decisions, principles, conflicts, deadlines)
      NO  → rebuild static (~5ms)
    
    ctx.semantic(user_message) → relevant context (~20ms)
    
    assemble prompt:
      base_system_prompt
      + <memory_context>...</memory_context>
      + tool_instruction (if model supports tools)

[3] Conductor → LLM:
    system = assembled prompt
    messages = conversation history
    tools = mcp_tools (if supported)

[4] LLM → response (+ optional tool_calls)

[5] If tool_calls:
    Conductor executes tools → returns results → LLM continues

[6] Observer.process_async(
      user_message,
      assistant_response,
      tool_calls,        ← Observer видит ВСЕ tool calls
      tool_results       ← и результаты
    )

[7] Response → User
```

**Overhead:** ~20-25ms на шаге [2]. Незаметно на фоне 1-10 секунд LLM latency.

---

## 8. Первая сессия (пустая память)

```xml
<memory_context updated="2026-03-25T14:32:00Z">
<status>First session. Memory is empty — learning from this conversation.</status>
</memory_context>
```

Не пустота. Агент понимает что система работает. Observer начинает записывать с первого сообщения.

---

## 9. API: ctx.inject()

Для Embedded mode (разработчик интегрирует вручную):

```python
from mnemostroma import ctx

# Перед каждым вызовом LLM:
memory_block = ctx.inject(
    user_message="как реализовать refresh tokens?",
    max_tokens=600,
    include_tools=True   # вернуть и tool definitions
)

# memory_block.context  → XML строка для system prompt
# memory_block.tools    → list[dict] tool definitions
# memory_block.stats    → {"tokens": 423, "cached": True, "semantic_ms": 18}
```

Для Daemon mode — Conductor делает это автоматически.

---

## 10. Почему это не ломается

| Бывший провал | Почему не происходит |
|--------------|---------------------|
| Агент забыл вызвать ctx_active() | Не нужно вызывать — Conductor подставляет контекст |
| Tool result не распарсен | Базовый контекст уже в prompt, tools — бонус |
| Injection вытеснен из контекста | Conductor пересобирает prompt при каждом вызове |
| Дублирование injection + tool | memory_context = summary, tools = детали. Разные уровни |
| Observer не видит tool calls | Conductor proxy видит всё |
| Re-injection без объяснения | Нет re-injection — prompt собирается каждый раз заново |
| Первая сессия = пустота | Friendly empty state в memory_context |

---

*Mnemostroma | Agent Integration Specification | v2.0 | 2026-03-25*
*Conductor proxy pattern: контекст гарантирован, tools — для глубокого доступа*
