# Release Notes — Mnemostroma v2.5.3

> **Дата:** 2026-07-29

v2.5.3 is a quality and lifecycle release focused on memory scoring correctness, NER stability, and restoring the relevance channel.

## What's new

### Relevance scoring via intent_vector
- `SystemContext.current_intent_vector` stores the embedding of the last search query
- `search.py` saves the query embedding after each `semantic_search()` call
- `conductor.py` and `gateway/server.py` pass `intent_vector` to `observer_pipeline()`
- New sessions created from a search context now compute `relevance = dot(session_embedding, intent_vector)` instead of defaulting to 0.5

### NER lifecycle hardening
- `BertNER.load()` is now idempotent with thread-safe lock — no more duplicate ONNX InferenceSession creation
- `BertNER.close()` requires `shutdown=True` — prevents accidental session teardown mid-lifecycle
- Instance counter (`_instances_created`, `_instance_id`) and load counter (`_load_count`) for diagnostics

### Memory scoring fixes
- **Removed** `calculate_score(0.5, ...)` from consolidation — was overwriting all session scores every 300s with hardcoded relevance
- **Added** `calculate_retention_score()` — age/importance/feedback/usage based, no query relevance component, used for eviction
- **Fixed** score logging: `T` now shows real temporal decay instead of hardcoded 1.0
- **Fixed** feedback signal analysis: `signal` → `type` field in log analyzer

### Infrastructure
- Systemd `MemoryMax` raised to 1000M, `MemoryHigh` to 850M — eliminates OOM-kill cascade from 750M hard limit
- cgroup observability: memory snapshots + pmap at 650/700MB thresholds
- `duckdbInstallEnv()`: strips TLS-affecting env vars from DuckDB installer child process

## Upgrade notes

No breaking changes. All new fields are optional (`None` by default). Existing setups continue to work without modification.

## Stats

| Metric | Value |
|--------|-------|
| Tests | 1556 |
| OOM kills | 0 |
| BertNER instances/PID | 1 |
| Feedback valid signals | 19 (0 None) |

**v2.5.3** | 1556 tests passing | 0 regressions | Relevance + Memory Quality Release
