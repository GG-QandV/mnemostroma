# Mnemostroma
## The memory layer for AI agents
## v1.7.1 | 2026-04-07 | Phase 9.2 Complete

Mnemostroma is a lightweight, RAM-first context management layer for AI agents and LLM-powered applications.

It runs as an autonomous sidecar — no framework, no cloud, no GPU required. While your agent works, Mnemostroma silently observes, indexes, and manages everything worth remembering. Your agent never writes context manually.

---

### Architecture in one sentence

A dual-stream async pipeline (Observer + Content) backed by 4 memory layers, numpy MatrixSearch ANN, ONNX INT8 inference stack, and a formal PersistenceLayer (SQLite WAL) — all in ~631MB RAM, ~20ms retrieval latency, fully offline.

---

### Core components (v1.7.1)

| Component | Role |
|---|---|
| **Observer** | Async sidecar coroutine. Watches agent I/O, extracts entities via HybridNER, embeds with multilingual-e5-small INT8, scores and indexes. |
| **PersistenceLayer** | Formal I/O layer (Phase 9.2). Ensures atomic disk updates (RAM ⊆ DISK) and manages SQLite WAL connections. |
| **Subconscious** | Memory lifecycle manager (Stage C/D). Includes **Decay Engine** (forgetting) and **Dreamer** (background re-evaluation). |
| **Tuner** | Dissonance detector. Flags conflicts, semantic drift, and stale anchors. |
| **Conductor** | Orchestrator. Managed User Mode (CLI), bootstrap, event loops, and RAM health. |

---

### ONNX INT8 Stack — ~631MB RSS, No Torch

| Model | Role | RAM |
|---|---|---|
| multilingual-e5-small | Session & Content vectorisation (384d) | ~420MB |
| HybridNER (DistilBERT) | Zero-shot Entity Extraction | ~170MB |
| TinyBERT-L2-v2 | Cross-encoder reranking (lazy load) | 8MB |
| **Total (RSS)** | Including Runtime & Tokenizers | **~631MB** |

---

### Retrieval pipeline latency (CPU-only)

```
ctx.active()           < 0.01ms   RAM dict
ctx.search([tags])     < 0.1ms    RAM dict filter
ctx.semantic(query)    ~ 20ms     embed(10ms) → MatrixSearch(0.5ms) → Rerank(6ms)
ctx.bridge()           < 0.01ms   session handoff packet
```

---

### Roadmap Status

- **v1.6.2** ✅ Subconscious core (Stage C/D) + Experience Layer.
- **v1.7.0** ✅ MatrixSearch (replaced HNSWlib) + Multi-task stability.
- **v1.7.1** ✅ **PersistenceLayer Split** (Phase 9.2) + **CLI User Mode**.

---

### Deployment

**CLI**: `mnemostroma setup / on / off / status`
**SDK**: `from mnemostroma import ctx`
No Docker · No cloud · No API keys · 303/303 Tests Passed.

---

*Mnemostroma — the memory layer for AI agents*
*μνήμη + στρῶма · offline · ~631MB · ~20ms · stable*
