# MNEMOSTROMA SYSTEM ASSESSMENT
## Complete Architecture & Resource Allocation

### 1. CORE COMPONENTS & RAM ALLOCATION

| Component | Role | RAM Baseline | RAM Peak | Purpose |
|-----------|------|------------|---------|---------|
| **Observer** | Session capture & async ingestion | ~80 MB | ~150 MB | Watches all I/O, extracts entities in real-time (non-blocking) |
| **Dreamer** | Background distillation & consolidation | ~60 MB | ~120 MB | Processes context, applies decay, indexes compression |
| **Matrix Search** (ANN/HNSW) | Semantic retrieval index | ~140 MB | ~180 MB | 384-dim embeddings, ~20ms latency per query |
| **Memory Strata** | Multi-layer storage orchestration | ~120 MB | ~200 MB | Manages 5 layers: RAM Hot, Ledger, Experience, Subconscious, Archive |
| **IPC Server** | Socket-based tool communication | ~15 MB | ~40 MB | Daemon ↔ Client (MCP protocol, async) |
| **Session Index** | Active session tracking & routing | ~25 MB | ~50 MB | Quick lookup by ID, tag, timestamp |
| **Tuner** (Conflict/Drift) | Semantic drift detection, constraint verification | ~35 MB | ~80 MB | Monitors model consistency, catches contradictions |
| **Persistence Layer** | SQLite WAL writes & versioning | ~50 MB | ~100 MB | Async batch flushes, incremental vacuum |
| **Content Versioning** | Artifact diff tracking (code, docs, configs) | ~30 MB | ~60 MB | Stores diffs + metadata (why_changed, author) |
| **Feedback Engine** | Implicit signal processing (USE/REVISIT/IGNORE) | ~20 MB | ~40 MB | EMA weighting, recency bias correction |
| **Other (CLI, logging, cache)** | Utilities, health monitor, local diagnostics | ~30 MB | ~50 MB | Watch UI, tray, daemon lifecycle |
| **TOTAL BASELINE** | - | **~605 MB** | - | Within 650 MB budget |
| **TOTAL PEAK** | - | - | **~1,070 MB** | Can spike to 750 MB hard limit during compression cycles |

---

### 2. NEURAL MODELS & EMBEDDING PIPELINE

| Model Name | Size (INT8) | Dimensions | Latency | Role | Architecture |
|----------|-----------|-----------|---------|------|-------------|
| **multilingual-e5-small** | 117 MB | 384d | ~15ms (cold), ~2ms (warm) | Session + content embedding, semantic search | ONNX (4-layer BERT) |
| **distilbert-ner** | 60 MB | - | ~8ms | Named entity recognition (NER), precision extraction | ONNX (distilled 6-layer) |
| **tinybert-l2-v2** | 7 MB | - | ~5ms | Cross-encoder reranking (lazy load) | ONNX (2-layer, compress-only) |
| **TOTAL MODEL FOOTPRINT** | **184 MB** | - | - | Downloaded once at setup, shared across all sessions | - |

---

### 3. STORAGE & DATABASE LAYERS

| Layer | Type | Max Size | Retention | Purpose |
|-------|------|----------|-----------|---------|
| **RAM Hot** (L0) | In-memory dict | ~50 MB | Current session | Immediate context, 20ms retrieval |
| **Ledger** (L1) | SQLite, indexed | ~100 MB | Unbounded (facts never expire) | Immutable data: dates, URLs, names, exact quotes |
| **Experience** (L2) | SQLite, ANN-indexed | ~150 MB | 90 days (configurable) | Mid-term working context, fading with time |
| **Subconscious** (L3) | SQLite, embedding-only | ~100 MB | 36,500 days (principles) | Eternal rules, constraints, core knowledge (shape-only, no content) |
| **Archive** (L4) | SQLite.bak, compressed | ~200 MB | 3+ years | Cold storage, rarely accessed, auto-vacuum eligible |
| **SQLite Cache** | mmap + page cache | 64 MB | - | Query acceleration, read-ahead prefetch |
| **TOTAL STORAGE BUDGET** | - | **500 MB+ (disk)** | - | Does not count against RAM; grows ~2 MB/day |

---

### 4. RESOURCE LIMITS & POLICIES

| Parameter | Value | Context |
|-----------|-------|---------|
| **RAM Budget (default)** | 650 MB | Recommended for production |
| **RAM Soft Limit** | 700 MB | Trigger light eviction (background task) |
| **RAM Hard Limit** | 750 MB | Force eviction, reject new sessions if needed |
| **Eviction Threshold** | 80% (520 MB) | Start aggressive compression |
| **Session Window** | 200 entries | ~50-100 KB per entry |
| **Content Max Blocks** | 500 artifacts | Auto-prune oldest on overflow |
| **DB Growth Budget** | 2 MB/day | ~730 MB/year (capped) |
| **SQLite Compression** | 500 MB threshold | Auto-archive ≥500 MB databases |
| **SQLite Auto-Vacuum** | INCREMENTAL | Defragment in 50-entry batches |
| **Async Flush Interval** | 5 seconds | Batch writes to disk (not real-time) |
| **Backup Interval** | 3 hours | Incremental snapshots to `~/.mnemostroma/backups/` |

---

### 5. COMPUTATIONAL CONFIGURATION

| Setting | Value | Impact |
|---------|-------|--------|
| **ONNX Threads (inter)** | 2 | Parallelism across neural cores |
| **ONNX Threads (intra)** | 2 | Within-operation parallelism |
| **Embedding Dim** | 384 | HNSW vector size, balanced speed/precision |
| **Top-K Candidates** | 20 | Pre-filter before reranking |
| **Top-N Results** | 5 | Final result set size |
| **Pipeline Width** | 2 | Concurrent embedding batches |
| **NER Call Rate** | 30% | Probabilistic entity extraction (not every message) |
| **Conflict Threshold** | 0.75 | Contradiction detection sensitivity |
| **Drift Threshold** | 0.35 | Semantic drift detection |
| **Reranker (TinyBERT)** | Lazy-loaded | Loaded only on demand, ~5ms first call |

---

### 6. MEMORY LAYERS DECAY SCHEDULE

| Layer | Age 1d | Age 7d | Age 30d | Age 90d | Age 1y |
|-------|--------|--------|---------|---------|--------|
| **RAM Hot (L0)** | 100% detail | *archived* | *gone* | - | - |
| **Ledger (L1)** | 100% | 100% | 100% | 100% | 100% |
| **Experience (L2)** | 100% detail | 95% | 60% | *archived* | *gone* |
| **Subconscious (L3)** | 100% embedding | 100% | 100% | 100% | 100% |
| **Archive (L4)** | - | - | *compressed* | *cold* | *cold* |

**Decay Functions (λ):**
- Critical (Principles): λ = 0.05 (slowest fade)
- Important (Decisions): λ = 0.15
- Background (Noise): λ = 0.40 (fastest fade)
- Principles (Constraints): λ = 0.0 (never fade)

---

### 7. LATENCY PROFILE (Percentiles)

| Operation | p50 | p95 | p99 | Notes |
|-----------|-----|-----|-----|-------|
| Semantic search (ctx_semantic) | 18 ms | 25 ms | 42 ms | Includes embedding + ANN query |
| Anchor lookup (ctx_anchors) | 0.1 ms | 0.5 ms | 2 ms | In-memory hash table |
| Tag search (ctx_search) | 0.8 ms | 3 ms | 8 ms | Indexed SQLite query |
| Context injection (ctx_bridge) | 1 ms | 5 ms | 12 ms | Serialization overhead |
| Observer write (async) | 0 ms | - | - | Fire-and-forget, flushes every 5s |
| Entity extraction (NER) | 8 ms | 12 ms | 20 ms | Called at ~30% rate |
| Dreamer cycle (background) | 100 ms | 300 ms | 500 ms | Runs every 5 min when idle |

---

### 8. SUPPORTED CLIENT INTEGRATIONS

| Client | Protocol | Overhead | Status |
|--------|----------|----------|--------|
| Claude Desktop | MCP (stdio) | ~5 MB adapter per instance | ✓ Stable |
| Claude Code (CLI) | MCP (stdio) | ~5 MB adapter | ✓ Stable |
| VS Code (Copilot) | MCP (stdio) | ~5 MB adapter | ✓ Stable |
| Cursor / Windsurf | MCP (stdio) | ~5 MB adapter | ✓ Stable |
| Cline / Zed / Continue | MCP (stdio) | ~5 MB adapter | ⚠ Limited testing |
| claude.ai (web) | SSE + browser ext | Proxy: ~70 MB | ✓ Beta |
| Custom LLM (via Anthropic SDK) | Direct socket | None | ✓ Stable |

**Note:** Multiple clients can connect simultaneously; each spawns its own lightweight adapter sharing a single daemon.

---

### 9. INSTALLATION PROFILES

| Profile | Core Size | With Models | Total Disk | RAM Footprint |
|---------|-----------|-------------|-----------|---------------|
| **Minimal** | 15 MB | - | 15 MB | 100 MB (no models) |
| **Base** (pip install) | 15 MB | 184 MB | 199 MB | 420 MB baseline |
| **All** (with [tray]) | 16 MB | 184 MB | 200 MB | 420 MB baseline |
| **With [sse] + proxy** | 17 MB | 184 MB | 201 MB | 420 MB + 70 MB proxy |
| **Full (all + extras)** | 17 MB | 184 MB | 201 MB | 420 MB + 70 MB proxy |

---

### 10. SUMMARY DASHBOARD

```
┌─ MNEMOSTROMA v1.8.2 RESOURCE MAP ────────────────────────────┐
│                                                                 │
│  Component Footprint:        ~605 MB baseline                 │
│  Model Zoo:                  184 MB (downloaded once)          │
│  Peak Usage:                 ~750 MB (hard limit)             │
│  Sustainable Daily Growth:   ~2 MB/day (configurable)         │
│                                                                 │
│  Retrieval Latency:          ~20 ms (semantic)                │
│  Entity Extraction:          ~8 ms (NER, 30% of messages)     │
│  Reranking:                  ~5 ms (TinyBERT, lazy-loaded)    │
│                                                                 │
│  Memory Layers:              5 (RAM Hot → Subconscious)       │
│  Retention:                  1 day → 36,500 days              │
│  Decay Schedule:             λ(critical)=0.05 → λ(noise)=0.4 │
│                                                                 │
│  Supported Clients:          7+ IDE/web integrations          │
│  Adapter Overhead:           ~5 MB per connected client       │
│                                                                 │
└─────────────────────────────────────────────────────────────┘
```

---

### 11. PERFORMANCE TUNING KNOBS

**To reduce RAM usage:**
- Set `ram_budget_mb: 420` (baseline only)
- Reduce `session_window_size: 100` (lose recent context)
- Disable `experience.layer_enabled: false` (lose mid-term memory)

**To reduce latency:**
- Increase `onnx_intra_threads: 4` (if CPU available)
- Set `search.top_k_candidates: 10` (faster filtering)
- Enable `temporal_retrieval.time_weighted_search: true` (temporal bias)

**To extend storage:**
- Increase `db_growth_budget_mb_per_day: 5.0` (more disk writes)
- Increase `content_max_blocks: 1000` (store more artifacts)
- Increase `SQLite_Archive` if cloud sync enabled

---

**Generated:** 2026-04-18
**Mnemostroma:** The memory layer for AI agents
**v1.8.2** | Offline-first | 419 tests passing
