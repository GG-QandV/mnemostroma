# Mnemostroma
## The memory layer for AI agents

Mnemostroma is a lightweight, RAM-first context management layer
for AI agents and LLM-powered applications.

It runs as an autonomous sidecar — no framework, no cloud, no GPU required.
While your agent works, Mnemostroma silently observes, indexes, and manages
everything worth remembering. Your agent never writes context manually.
It just works.

---

### Architecture in one sentence

A dual-stream async pipeline (Observer + Content) backed by
three memory layers (semantic / anchor / precision), HNSWlib ANN search,
ONNX INT8 inference stack, and SQLite WAL cold storage —
all in ~600MB RAM, ~20ms retrieval latency, fully offline.

---

### What it solves

LLM context windows are stateless by design.
Every new session starts from zero.
RAG retrieves documents, not decisions.
Vector databases store content, not meaning.

Mnemostroma stores what the agent *learned* —
decisions, blockers, principles, deadlines —
and surfaces the right memory at the right moment
without the agent asking for it.

---

### Core components

| Component | Role |
|---|---|
| **Observer** | Async sidecar coroutine. Watches agent I/O, extracts entities via GLiNER NER, embeds with EmbeddingGemma-300M INT8, scores and indexes — without blocking the agent |
| **Dissolver** | Memory density manager. Adjusts resolution (1.0→0.05) across 5 layers based on age, use frequency, and successor sessions. Embeddings never deleted |
| **Tuner** | Dissonance detector. Flags conflicts, semantic drift, expired anchors, stale embeddings |
| **Conductor** | Orchestrator. Bootstrap, event loop, RAM budgeting, health checks |
| **Session Bridge** | Handoff packet for new sessions or agent switches. Instant context restore |

---

### ONNX INT8 stack — 342MB total, no torch

| Model | Role | RAM |
|---|---|---|
| EmbeddingGemma-300M | Session vectorisation (512d MRL) | 52MB |
| BGE-M3 | Content vectorisation (dense+ColBERT) | 145MB |
| GLiNER-small-v2.1 | Zero-shot NER | 42MB |
| TinyBERT-L-2-v2 | Cross-encoder reranking | 8MB |

---

### Memory layers

```
RAM Hot    resolution > 0.8   full brief + anchors + precision + embedding
RAM Warm   resolution 0.5–0.8 brief + tags + anchors
SQLite Deep           0.3–0.5 brief(20) + tags(2) + embedding
SQLite Archive        0.1–0.3 brief(20) + embedding
SQLite Eternal        ≤ 0.05  embedding only (HNSWlib: eternal)
```

Principles (importance=principle) never dissolve. Never evicted.

---

### Retrieval pipeline latency (CPU-only)

```
ctx.active()           < 0.01ms   RAM dict
ctx.search([tags])     < 0.1ms    RAM dict filter
ctx.semantic(query)    ~ 20ms     tokenise → embed → HNSW top-20 → rerank → brief×5
ctx.bridge()           < 0.01ms   session handoff packet
```

---

### Urgency & principles (v1.3)

Four urgency levels (none / deadline_h / deadline_d / deadline_w).
Expired deadlines automatically penalise score ×0.5.
Principle-level memories boost score ×1.3, resist eviction permanently.
Dissolver check every 5 min. compress_to_bare_entity() on expiry.

---

### MCP API surface (18 tools)

Read: ctx.active() · ctx.get() · ctx.search() · ctx.semantic()
      ctx.anchors() · ctx.precision() · ctx.full() · ctx.bridge()
      ctx.urgent() · ctx.expire()
Write: ctx.save() · ctx.update() · ctx.flag() · ctx.precision()
       content.save() · content.tag()
Admin: ctx.decay() · ctx.evict() · ctx.sync() · ctx.status()
       ctx.growth() · ctx.pulse() · ctx.configure()

---

### Deployment

Embedded Python library · Daemon (stdio MCP) · CLI
No Docker · No cloud · No API keys · Runs on a laptop

---

### Roadmap

v1.x  MVP — Observer + Session Index + Bridge
v1.3  ✅ Urgency Policy + Principle protection
v1.5  Implicit feedback (use_count correlation)
v2.0  Explicit feedback loop + adaptive score weights
v3.0  Subconscious layer — Hypómnema Strōma
      (latent topic graph, associative mesh, anomaly scoring)

---

*Mnemostroma — the memory layer for AI agents*
*μνήμη + στρῶμα · offline · ~600MB · ~20ms · no GPU*
