# Mnemostroma API Reference

**Version: 1.8.4 | Date: 2026-04-23**

Core API for embedding Mnemostroma memory into Python applications.

---

## Module: `mnemostroma`

Main entry point for using Mnemostroma as a library.

### `Conductor`

Central orchestrator that manages the memory system lifecycle.

#### Constructor
```python
Conductor(config_dir: str | None = None, log_level: str = "INFO")
```

**Parameters:**
- `config_dir` — Override default `~/.mnemostroma/`. Useful for testing.
- `log_level` — Logging level (DEBUG, INFO, WARNING, ERROR). Default: INFO.

**Example:**
```python
from mnemostroma import Conductor
conductor = Conductor()
```

---

#### Method: `start()`

Initialize the memory system and load models.

```python
async def start() -> None
```

**Behavior:**
1. Load configuration from `~/.mnemostroma/config.json`
2. Initialize embedding models (INT8 ONNX)
3. Connect to daemon (or start if not running)
4. Load SQLite indices into RAM

**Raises:**
- `RuntimeError` — If daemon not responding or models fail to load

**Example:**
```python
await conductor.start()
```

**Latency:** ~500ms (models lazy-load)

---

#### Method: `shutdown()`

Gracefully shut down the memory system.

```python
async def shutdown() -> None
```

**Behavior:**
1. Flush pending observations to disk
2. Close database connections
3. Unload models (free RAM)
4. Leave daemon running (for next session)

**Example:**
```python
try:
    await conductor.start()
    # ... use conductor ...
finally:
    await conductor.shutdown()
```

---

#### Method: `inject()`

Retrieve memory context for the current session.

```python
def inject(user_id: str | None = None, top_k: int = 10) -> str
```

**Parameters:**
- `user_id` — Scope memory to specific user. Default: global context.
- `top_k` — Number of top-k similar memories to include. Default: 10.

**Returns:**
- String containing relevant memory snippets, formatted for LLM consumption.

**Behavior:**
1. Compute embedding of recent session context
2. Search SQLite for top-k similar memories
3. Fetch anchors (hard constraints that never decay)
4. Format as readable text for prompt injection

**Raises:**
- `RuntimeError` — If conductor not started

**Example:**
```python
memory_context = conductor.inject(user_id="alice")
prompt = f"Previous context:\n{memory_context}\n\n{user_message}"
```

**Latency:** ~20ms (semantic search)

**Returns example:**
```
## Recent Context
- User prefers Python over Java
- Working on ML model deployment
- Budget constraint: 700MB RAM

## Anchors (Non-Negotiable Rules)
- Never use external APIs
- Always validate user input
```

---

#### Method: `observe()`

Capture an interaction (transcript) in memory.

```python
async def observe(transcript: dict | str) -> None
```

**Parameters:**
- `transcript` — Dict or JSON string containing interaction data.

**Transcript Structure:**
```python
{
    "messages": [  # list of message dicts
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."},
    ],
    "user_id": "alice",  # optional, for multi-tenant
    "timestamp": "2026-04-17T10:30:00Z",  # optional
    "metadata": {"source": "api", "model": "claude-opus"}  # optional
}
```

**Behavior:**
1. Validate transcript format
2. Extract entities (PER, ORG, LOC, TECH, DECISION, etc.)
3. Compute embeddings for content
4. Insert into SQLite with compression
5. Update vector index asynchronously

**Raises:**
- `ValueError` — If transcript malformed
- `RuntimeError` — If not started

**Example:**
```python
await conductor.observe({
    "messages": [
        {"role": "user", "content": "What's the status of the migration?"},
        {"role": "assistant", "content": "The migration is 80% complete..."}
    ]
})
```

**Latency:** ~100ms (async background embedding)

---

#### Method: `set_last_message()`

Store the user's most recent message for same-turn signal detection.

```python
def set_last_message(message: str) -> None
```

**Parameters:**
- `message` — The user's latest input

**Use Case:**
Helps memory system detect when the same user repeats themselves (e.g., "Did you forget what I just asked?").

**Example:**
```python
conductor.set_last_message("Let's discuss the budget constraints")
```

---

#### Property: `is_idle`

Check if no observations received in recent time window.

```python
@property
def is_idle() -> bool
```

**Returns:**
- `True` if no `observe()` call for > idle_threshold (default: 5min)
- `False` otherwise

**Use Case:**
Detect end of conversation or pause in interaction.

**Example:**
```python
if conductor.is_idle:
    print("User hasn't sent a message in 5+ minutes")
```

---

#### Property: `ctx`

Access the internal `SystemContext` (advanced).

```python
@property
def ctx() -> SystemContext
```

**Contains:**
- `persistence` — SQLite connection + paths
- `embedder` — Embedding model interface
- `ner` — Named entity extractor
- `anchors` — Hard constraints storage

**Warning:**
This is internal API. Use only for advanced scenarios (debugging, custom queries).

---

### `SystemContext`

Internal system context (accessed via `conductor.ctx`).

#### Properties

**`ctx.persistence`**
- `db_path` — Path to SQLite database
- `get_recent_interactions(days: int)` — Query recent data

**`ctx.embedder`**
- `embed(text: str)` → `np.ndarray` — Get embedding vector
- `search(query_embedding: np.ndarray, top_k: int)` → `list[dict]` — Vector search

**`ctx.ner`**
- `extract(text: str)` → `list[dict]` — Extract entities

---

## Example: Full Lifecycle

```python
import asyncio
from mnemostroma import Conductor

async def main():
    # 1. Initialize
    conductor = Conductor()
    await conductor.start()
    
    try:
        # 2. Retrieve context for prompt
        context = conductor.inject(user_id="user_123")
        
        # 3. Use in LLM call (pseudocode)
        response = llm.generate(
            prompt=f"Context:\n{context}\n\nUser: {user_input}"
        )
        
        # 4. Capture for next session
        await conductor.observe({
            "messages": [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": response}
            ]
        })
        
        # 5. Check if session ended
        if conductor.is_idle:
            print("Conversation paused")
            
    finally:
        # 6. Clean shutdown
        await conductor.shutdown()

asyncio.run(main())
```

---

## Error Handling

### Common Exceptions

#### `RuntimeError: Conductor not started`
**Cause:** Called a method before `await conductor.start()`

**Solution:**
```python
await conductor.start()  # Call this first
context = conductor.inject()
```

---

#### `RuntimeError: Daemon not responding`
**Cause:** Mnemostroma daemon crashed or isn't running

**Solution:**
```bash
# Check status
mnemostroma status

# Restart if needed
mnemostroma off && mnemostroma on

# Check logs
mnemostroma logs --days 1
```

---

#### `ValueError: Invalid transcript format`
**Cause:** Transcript dict missing required fields

**Solution:** Ensure transcript has this structure:
```python
{
    "messages": [
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ]
}
```

---

## Performance Notes

### Latencies
| Operation | Latency | Notes |
|-----------|---------|-------|
| `start()` | ~500ms | First load, lazy model init |
| `inject()` | ~20ms | Semantic search (p95) |
| `observe()` | ~100ms | Async embedding + insert |
| `shutdown()` | ~50ms | Flush + close |

### Memory
| Component | Size | Notes |
|-----------|------|-------|
| Conductor | ~420 MB | Daemon + models |
| Per user | ~10 KB | Embeddings index |
| SQLite | ~1 MB | Per 10K interactions |

### Scaling
- Single daemon: 100+ concurrent users
- Distributed: Run multiple daemons on different ports
- Sharding: Partition users by ID for 1000+ scale

---

## Advanced: Custom Configuration

Override defaults by creating `~/.mnemostroma/config.json`:

```json
{
  "models": {
    "embedder": "Xenova/multilingual-e5-small",
    "ner": "Xenova/distilbert-base-multilingual-cased-ner-hrl"
  },
  "storage": {
    "db_path": "/custom/path/logs.db"
  },
  "performance": {
    "max_ram_mb": 750,
    "embedding_batch_size": 32
  }
}
```

---

## Troubleshooting

### Memory not persisting between sessions

**Check:**
1. Is daemon running? → `mnemostroma status`
2. Is `observe()` being awaited? → Use `await conductor.observe(...)`
3. Check logs → `mnemostroma logs --days 1`

---

### Slow `inject()` calls

**Causes & solutions:**
- **Large SQLite** — Run `VACUUM` periodically
- **High load** — Increase `embedding_batch_size` in config
- **Disk I/O** — Move database to SSD

---

### Models not loading

**Check Python + ONNX runtime:**
```bash
python -c "import onnxruntime; print(onnxruntime.get_available_providers())"
```

Expected output: `['CUDAExecutionProvider', 'CPUExecutionProvider']` or at least `['CPUExecutionProvider']`

---

## Related Documentation

- **Integration Examples**: [INTEGRATION_EXAMPLES.md](./INTEGRATION_EXAMPLES.md)
- **Memory Model**: [MEMORY_SPEC_v2.md](./MEMORY_SPEC_v2.md)
- **MCP Tools**: [MCP_TOOLS_MAP.md](./MCP_TOOLS_MAP.md)
- **CLI Reference**: [README.md](../README.md#quick-start)

