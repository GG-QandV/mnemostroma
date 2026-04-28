# MNEMOSTROMA SYSTEM ASSESSMENT (v1.8.5)

## Complete Architecture & Resource Allocation

### 1. CORE COMPONENTS & RAM ALLOCATION

| Component                       | Role                                              | RAM Baseline | RAM Peak    | Purpose                                                              |
| ------------------------------- | ------------------------------------------------- | ------------ | ----------- | -------------------------------------------------------------------- |
| **Observer**                    | Session capture & async ingestion                 | ~40 MB       | ~80 MB      | Watches all I/O, extracts entities in real-time (non-blocking)       |
| **Dreamer**                     | Background distillation & consolidation           | ~30 MB       | ~60 MB      | Processes context, applies decay, indexes compression                |
| **Matrix Search** (ANN/Numpy)   | Semantic retrieval index                          | ~50 MB       | ~80 MB      | 384-dim embeddings, ~20ms latency per query                          |
| **Memory Strata**               | Multi-layer storage orchestration                 | ~40 MB       | ~70 MB      | Manages 5 layers: RAM Hot, Ledger, Experience, Subconscious, Archive |
| **IPC Server**                  | Socket-based tool communication                   | ~5 MB        | ~15 MB      | Daemon ↔ Client (MCP protocol, async)                                |
| **Session Index**               | Active session tracking & routing                 | ~10 MB       | ~20 MB      | Quick lookup by ID, tag, timestamp                                   |
| **Tuner** (Conflict/Drift)      | Semantic drift detection, constraint verification | ~10 MB       | ~25 MB      | Monitors model consistency, catches contradictions                   |
| **Persistence Layer**           | SQLite WAL writes & versioning                    | ~20 MB       | ~40 MB      | Async batch flushes, incremental vacuum                              |
| **Content Versioning**          | Artifact diff tracking (code, docs, configs)      | ~10 MB       | ~25 MB      | Stores diffs + metadata (why_changed, author)                        |
| **Feedback Engine**             | Implicit signal processing (USE/REVISIT/IGNORE)   | ~5 MB        | ~15 MB      | EMA weighting, recency bias correction                               |
| **Other (CLI, logging, cache)** | Utilities, health monitor, local diagnostics      | ~16 MB       | ~30 MB      | Watch UI, tray, daemon lifecycle                                     |
| **MODELS (Zoo)**                | Neural networks (INT8)                            | ~184 MB      | ~184 MB     | Shared ONNX sessions (Baseline 420 MB reached)                       |
| **TOTAL BASELINE**              | -                                                 | **~420 MB**  | -           | Optimized for v1.8.5 stabilization                                   |
| **TOTAL PEAK**                  | -                                                 | -            | **~650 MB** | Within 650 MB hard budget                                            |

---

### 2. NEURAL MODELS & EMBEDDING PIPELINE

| Model Name                | Size (INT8) | Dimensions | Latency                   | Role                                                 | Architecture                  |
| ------------------------- | ----------- | ---------- | ------------------------- | ---------------------------------------------------- | ----------------------------- |
| **multilingual-e5-small** | 117 MB      | 384d       | ~15ms (cold), ~2ms (warm) | Session + content embedding, semantic search         | ONNX (4-layer BERT)           |
| **distilbert-ner**        | 60 MB       | -          | ~8ms                      | Named entity recognition (NER), precision extraction | ONNX (distilled 6-layer)      |
| **tinybert-l2-v2**        | 7 MB        | -          | ~5ms                      | Cross-encoder reranking (lazy load)                  | ONNX (2-layer, compress-only) |
| **TOTAL MODEL FOOTPRINT** | **184 MB**  | -          | -                         | Downloaded once at setup, shared across all sessions | -                             |

---

### 3. RESOURCE LIMITS & POLICIES

| Parameter                | Value            | Context                                            |
| ------------------------ | ---------------- | -------------------------------------------------- |
| **RAM Budget (default)** | 650 MB           | Recommended for production                         |
| **RAM Soft Limit**       | 600 MB           | Trigger light eviction (background task)           |
| **RAM Hard Limit**       | 650 MB           | Force eviction, reject new sessions if needed      |
| **Regression Tests**     | 457/457 passed   | Full stability check (v1.8.5)                      |
| **Decision Coverage**     | 33%              | Significant improvement in anchor precision        |
| **Async Flush Interval** | 5 seconds        | Batch writes to disk (not real-time)               |
| **Backup Interval**      | 3 hours          | Incremental snapshots to `~/.mnemostroma/backups/` |

---

**Generated:** 2026-04-26
**Mnemostroma:** The memory layer for AI agents
**v1.8.5** | Offline-first | 457 tests passing
