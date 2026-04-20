# LATENCY_INVARIANTS.md
# Baseline: v1.7.5-pre-refactor
# Updated: Post-phase performance results

---

## Critical Path Budget

| Operation | Baseline | Budget | Extra Layers After Refactor | Allowed Overhead |
|:---|:---|:---|:---|:---|
| `ctx_semantic` (full) | ~20ms | 25ms hard cap | +1 (Port dispatch) | +0.05ms |
| `ctx_get` (RAM hit) | 0.01ms | 0.05ms | +1 (SessionPort.load) | +0.01ms |
| Observer full pipeline | ~32ms | 40ms | +6 (StepChain loop) | +0.06ms |
| `queue.put_nowait()` | <0.01ms | 0.05ms | none | — |
| SQLite batch flush | ~5ms | 8ms | +1 (BatchWriter) | +0.1ms |

---

## Queue Backpressure Rules

### Rule 1: Observer → Persistence Queue
- **Invariant:** If `queue.qsize() > 80%` of maxsize → `circuit_breaker.open()` mandatory.
- **Rule:** Do NOT block Observer (`put_nowait`).
- **Rule:** Do NOT lose data (log overflow).

### Rule 2: BatchWriter Flush Cycle
- **Invariant:** `FLUSH_INTERVAL=1.0s`, `BATCH_SIZE=50`.
- **Rule:** Explicit partial flush if interval expires.

### Rule 3: StepChain Synchronicity
- **Invariant:** `observer/pipeline.py` is a synchronous `for-loop`.
- **Forbidden:** No `asyncio.Queue` or `create_task` inside StepChain.

---

## Structural Red Flags (Automated)
- `await queue.put(` → BLOCKING: use `put_nowait()`.
- `aiosqlite` in `observer/steps/` → DIRECT IO in hot path.
- `asyncio.sleep` in pipeline → SLEEP in critical path.
