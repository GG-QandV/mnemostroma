# MNEMOSTROMA SYSTEM ASSESSMENT (v2.0.5)

## Complete Architecture, Ports allocation & Resource Footprint

> **Assessment note**: v2.0.5 is a major feature and security release introducing Server-Sent Events (SSE) adapter modules, a dual-client browser extension, and strict file authorization enforcements (`chmod 0o600`). The core search, embedding, and distillation pipelines have been thoroughly verified with 531 tests (up from 502).

---

### 1. Core Components, RAM Allocations & Active Listeners

| Component                       | Role                                              | RAM Baseline | RAM Peak    | Active Port / Binding                                                |
| ------------------------------- | ------------------------------------------------- | ------------ | ----------- | -------------------------------------------------------------------- |
| **Observer (v2.0)**            | Unified browser extension & DOM capturing          | ~45 MB       | ~90 MB      | Streams to port `8766` (Localhost)                                   |
| **SSE Adapter** *(embedded)*    | SSE MCP router — встроен в daemon (v2.3.2+)        | 0 MB extra   | 0 MB extra  | Port `8765` (Public, token-auth) / `8766` (Local, no-auth)           |
| **HTTP Adapter** *(embedded)*   | Streamable HTTP MCP router — встроен в daemon      | 0 MB extra   | 0 MB extra  | Port `8768` (Public, token-auth)                                     |
| **TLS Passthrough Proxy**       | HTTPS tunnel proxy (e.g. for Claude Code)          | ~10 MB       | ~25 MB      | Port `8767` (Localhost, self-signed TLS)                             |
| **Session Classifier**          | Session type classification (Code/Research)       | ~5 MB        | ~15 MB      | Internal pipeline only                                               |
| **Dreamer**                     | Background distillation & consolidation           | ~30 MB       | ~60 MB      | Background thread pools                                              |
| **AutoBridgeWorker**            | Autonomous background context pre-computation     | ~10 MB       | ~25 MB      | Precomputes sub-50ms handoffs                                        |
| **Matrix Search** (ANN/Numpy)   | Semantic + Temporal retrieval index               | ~55 MB       | ~90 MB      | 384-dim embeddings + Temporal SQL hybrid (~20ms latency)             |
| **Memory Strata**               | Multi-layer storage orchestration                 | ~40 MB       | ~70 MB      | Manages 5 layers: RAM Hot, Ledger, Experience, Subconscious, Archive |
| **IPC Server**                  | Socket-based tool communication                   | ~5 MB        | ~15 MB      | Unix Socket / Named Pipe (Daemon ↔ Client, MCP, async)               |
| **Persistence Layer**           | SQLite WAL writes & versioning                    | ~25 MB       | ~50 MB      | Automatic transactional content flushes                              |
| **Models (Zoo)**                | Neural networks (INT8)                            | ~100 MB      | ~185 MB     | Shared ONNX sessions (Optimized for idle CPU usage)                  |
| **TOTAL BASELINE**              | -                                                 | **~340 MB**  | -           | Highly optimized idle footprint                                      |
| **TOTAL PEAK**                  | -                                                 | -            | **~650 MB** | Within 650 MB hard budget                                            |

---

### 2. Network Interface Allocation

| Interface (Port) | Target Binding | Protocol | Authorization | Client Type | Purpose |
| ---------------- | -------------- | -------- | ------------- | ----------- | ------- |
| **HTTP Port 8768**| `127.0.0.1`   | HTTP     | Bearer Token  | VS Code, Antigravity, OpenCode, Qoder | Streamable HTTP MCP (основной транспорт). |
| **SSE Port 8765**| `127.0.0.1`    | HTTP/SSE | Bearer Token  | Cursor, Claude Code, Grok, Perplexity | SSE MCP transport. |
| **OBS Port 8766**| `127.0.0.1`    | HTTP/POST| None (local)  | Browser Extension | Receives raw DOM-parsed chat streams. |
| **TLS Port 8767**| `127.0.0.1`    | HTTPS    | None (local)  | CLI Clients (`Claude Code`) | Intercepts, observes, and forwards API queries. |

---

### 3. Neural Models & Embedding Pipeline

| Model Name                | Size (INT8) | Dimensions | Latency                   | Role                                                 | Architecture                  |
| ------------------------- | ----------- | ---------- | ------------------------- | ---------------------------------------------------- | ----------------------------- |
| **multilingual-e5-small** | 117 MB      | 384d       | ~15ms (cold), ~2ms (warm) | Session + content embedding, semantic search         | ONNX (4-layer BERT)           |
| **distilbert-ner**        | 60 MB       | -          | ~8ms                      | Named entity recognition (NER), precision extraction | ONNX (distilled 6-layer)      |
| **tinybert-l2-v2**        | 7 MB        | -          | ~5ms                      | Cross-encoder reranking (lazy load)                  | ONNX (2-layer, compress-only) |
| **TOTAL MODEL FOOTPRINT** | **184 MB**  | -          | -                         | Downloaded once at setup, shared across all sessions | -                             |

---

### 4. Operational Limits & Resource Policies

| Parameter                | Value            | Context                                            |
| ------------------------ | ---------------- | -------------------------------------------------- |
| **RAM Budget (default)** | 650 MB           | Recommended for production                         |
| **RAM Hard Limit**       | 650 MB           | Evicts cold vectors, holds transaction WALs        |
| **Regression Tests**     | 531/531 passed   | 100% Green (v2.0.5)                                |
| **Credential Protection**| `0600 (POSIX)`   | Automatic token file locking during initialization |
| **Active Tunneling**     | Optional (CF)    | Controlled via Cloudflare tunnels                  |
| **Release Guards**       | DOM-Only         | Default mode for public distribution               |
| **Context Handoff**      | < 50ms           | Accelerated by AutoBridgeWorker background cache   |
| **Backup Interval**      | 3 hours          | Incremental database backups                       |

---

**Generated:** 2026-05-17  
**Mnemostroma:** The offline-first memory layer for AI agents  
**v2.0.5** | Major Integration & Security Release | 531 tests passing
