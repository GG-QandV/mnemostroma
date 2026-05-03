# MNEMOSTROMA SYSTEM ASSESSMENT (v1.11.1)

## Complete Architecture & Resource Allocation

> **Patch note**: v1.11.1 is an installer stability patch. All component specs, RAM allocations, and model footprints are identical to v1.11.0. The only changes are in the installation pipeline (`install-daemon.sh`, `cli/commands.py`, `service_templates/`).

---

### 1. CORE COMPONENTS & RAM ALLOCATION

| Component                       | Role                                              | RAM Baseline | RAM Peak    | Purpose                                                              |
| ------------------------------- | ------------------------------------------------- | ------------ | ----------- | -------------------------------------------------------------------- |
| **Observer (v1.11)**            | Autonomous session capture (Mechanism #12)        | ~45 MB       | ~90 MB      | Automatically routes code/research to Content Branch                 |
| **Session Classifier**          | Session type classification (Code/Research)       | ~5 MB        | ~15 MB      | Powers autonomous routing decisions                                  |
| **Dreamer**                     | Background distillation & consolidation           | ~30 MB       | ~60 MB      | Processes context, applies decay, indexes compression                |
| **AutoBridgeWorker**            | Autonomous background context pre-computation     | ~10 MB       | ~25 MB      | Enables sub-50ms session handoffs between agents                     |
| **Matrix Search** (ANN/Numpy)   | Semantic + Temporal retrieval index               | ~55 MB       | ~90 MB      | 384-dim embeddings + Temporal SQL hybrid (~20ms latency)             |
| **Memory Strata**               | Multi-layer storage orchestration                 | ~40 MB       | ~70 MB      | Manages 5 layers: RAM Hot, Ledger, Experience, Subconscious, Archive |
| **IPC Server**                  | Socket-based tool communication                   | ~5 MB        | ~15 MB      | Daemon ↔ Client (MCP protocol, async)                                |
| **Persistence Layer**           | SQLite WAL writes & versioning                    | ~25 MB       | ~50 MB      | Handles increased frequency of automated content flushes             |
| **Content Manager**             | Artifact diff tracking & automated capture        | ~15 MB       | ~35 MB      | Now driven by Observer (Mechanism #12)                               |
| **Feedback Engine**             | Implicit signal processing                        | ~5 MB        | ~15 MB      | EMA weighting, recency bias correction                               |
| **Models (Zoo)**                | Neural networks (INT8)                            | ~100 MB      | ~185 MB     | Shared ONNX sessions (Optimized for idle)                            |
| **TOTAL BASELINE**              | -                                                 | **~340 MB**  | -           | Highly optimized idle footprint                                      |
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
| **RAM Hard Limit**       | 650 MB           | Force eviction, reject new sessions if needed      |
| **Regression Tests**     | 502/502 passed   | Full stability check (v1.11.1)                     |
| **Autonomous Accuracy**  | ~94%             | Content vs Research vs Context classification      |
| **Temporal Precision**   | ~5ms             | SQL hybrid search latency                          |
| **Context Handoff**      | < 50ms           | Accelerated by AutoBridgeWorker background cache   |
| **Backup Interval**      | 3 hours          | Incremental snapshots to `~/.mnemostroma/backups/` |

---

**Generated:** 2026-05-03  
**Mnemostroma:** The memory layer for AI agents  
**v1.11.1** | Installer Stability Patch | 502 tests passing
