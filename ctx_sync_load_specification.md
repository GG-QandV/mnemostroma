# ctx.sync() и ctx.load() — Спецификация
## Mnemostroma | Статус: ЗАФИКСИРОВАНО | Дата: 2026-03-24

---

## ctx.sync()

**Purpose:** Force immediate flush of all pending RAM changes to SQLite WAL (normally async).

**Use cases:** before graceful shutdown, before cloud sync, before agent handoff.

```python
def ctx_sync(ram_index, pending_updates, db_conn, hnsw_content) -> dict:
    """
    Blocks until all pending writes are committed.
    Returns: {"flushed_sessions": int, "flushed_content": int, "wal_size_mb": float}
    Latency: depends on pending queue size, typically 10-200ms
    """
```

### Behavior

1. Drain `observer_queue` (wait for all pending async tasks)
2. Batch flush all `pending_updates` to SQLite
3. WAL checkpoint `PASSIVE` (non-blocking)
4. Save `content_hnsw.bin` to disk
5. Return stats

> **Note:** When called by Conductor during `graceful_shutdown`, uses `TRUNCATE` checkpoint instead of `PASSIVE`.

---

## ctx.load(session_id)

**Purpose:** Force load a specific session from SQLite cold storage into RAM (lazy load trigger).

**Use case:** agent knows it needs an archived session, wants it hot before `ctx.semantic()` call.

```python
def ctx_load(session_id: str, ram_index: dict, db_conn,
             hnsw_session) -> Optional[SessionBrief]:
    """
    If session_id already in RAM → return immediately (no-op).
    If in SQLite → load into RAM, add to HNSWlib if embedding present.
    If not found → return None.
    Latency: <0.5ms (RAM hit) / <5ms (SQLite load)
    """
```

### Behavior

1. Check RAM dict → hit → return `SessionBrief`
2. SQLite `SELECT` by `session_id`
3. If found: deserialize, add to `ram_index`, add embedding to `hnsw_session`
4. Apply `apply_layer()` based on resolution
5. If `session_window` full: evict lowest-score session first
6. Return `SessionBrief` or `None`

### SQLite Index

```sql
CREATE INDEX IF NOT EXISTS idx_sessions_pk ON sessions(session_id);
```

---

## Latency Table

| Operation               | Latency  | Notes                    |
|-------------------------|----------|--------------------------|
| ctx.sync() minimal      | ~10ms    | Empty pending queue      |
| ctx.sync() full flush   | ~200ms   | 200 pending updates      |
| ctx.load() RAM hit      | <0.5ms   | Already in RAM           |
| ctx.load() SQLite       | <5ms     | Cold load                |
