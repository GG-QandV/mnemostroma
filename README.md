# Mnemostroma

### The memory layer for AI agents

> *μνήμη (mnḗmē, memory) + στρῶμα (strôma, layer) — the substrate everything rests on.*

---

You open a new chat. Explain everything again.
The model has no idea what you decided last week.
What's blocked. What's off the table. What matters.

You're not talking to an agent. You're talking to a goldfish with a PhD.

**Mnemostroma fixes that.**

It sits between you and your AI — silent, invisible, always on.
You keep working. Mnemostroma watches, learns, remembers.

Next session? Your agent already knows the context.
No prompting tricks. No pasting logs. No "as I mentioned before."

---

## What it does

Every time you work with an AI agent, Mnemostroma:

- **Catches what matters** — decisions, constraints, key facts — automatically
- **Compresses it smartly** — not a transcript, a distilled memory
- **Surfaces it when relevant** — without you asking
- **Forgets gracefully** — old stuff fades, critical stuff stays forever
- **Works offline** — your memory, your machine, no cloud

---

## Architecture in one sentence

A dual-stream async pipeline (Observer + Content) backed by 4 memory layers,
numpy MatrixSearch ANN, ONNX INT8 inference, and a formal PersistenceLayer (SQLite WAL) —
all in ~600MB RAM, ~20ms retrieval, fully offline.

---

## How it works

```
Your Agent
    │
    ├── OBSERVER (async sidecar — writes)
    │     Watches all I/O, extracts entities, embeds, scores, indexes
    │     Agent never writes memory — Observer does it silently
    │
    ├── AGENT TOOLS (read-only)
    │     ctx.active()    → current context         <0.01ms
    │     ctx.semantic()  → find by meaning          ~20ms
    │     ctx.search()    → find by tags            <0.1ms
    │     ctx.bridge()    → session handoff packet  <0.01ms
    │
    └── CONTENT BRANCH (versioned artifacts)
          Code, chapters, configs — with diffs and why_changed
```

**The agent never writes memory.** It only reads and acts. Observer handles everything else.
**Core product is RAM-only by default** for speed. Reliability is guaranteed by a formal `PersistenceLayer` (Phase 9.2), which manages asynchronous SQLite WAL writes and provides a strict isolation boundary between memory logic and storage.

---

## Memory model

Mnemostroma doesn't archive — it **dissolves**.

```
Day 1:    Full detail — brief, anchors, precision data, embedding
Week:     Detail fades — precision moves to SQLite
Month:    Brief + tags + anchors remain
Year:     Brief + embedding only
Decade:   Embedding only — the shape of memory without content
```

What you use stays vivid. What you don't fades gradually.
Principles never dissolve. Decisions persist. Phone numbers expire.

This is not a database with TTL. This is how human memory works.

---

## Status

**Current:** v1.7.1 alpha | 2026-04-07

| Component                                | Status                                        |
| ---------------------------------------- | --------------------------------------------- |
| Core backend (Observer, Memory, Storage) | ✅ Implemented, 303/303 tests                 |
| Anchor Layer / Emotional Patterns        | ✅ Implemented                                 |
| Implicit Feedback (v1.5)                 | ✅ Implemented                                 |
| PersistenceLayer Split (Phase 9.2)       | ✅ Implemented (v1.7.1)                        |
| CLI User Mode (setup/on/off/status)      | ✅ Implemented (v1.7.1)                        |
| MCP Server (stdio)                       | ✅ Implemented                                 |
| Continuation Detection & Mention Type    | ✅ Implemented                                 |
| Decay Engine & Dreamer                   | ✅ Implemented (Stage C/D)                     |
| Model install CLI                        | ✅ Implemented                                 |

---

## Quick Start (User Mode)

```bash
pip install mnemostroma
mnemostroma setup        # Initialize ~/.mnemostroma/ and download models
mnemostroma on           # Start persistent memory daemon (background)
mnemostroma service install   # Register as systemd/launchd service (autostart)
mnemostroma status       # Check health, metrics, and RAM usage
mnemostroma off          # Stop daemon
```

### OS Support & Services
- **Linux**: Supported via `systemd` (user mode).
- **macOS**: Supported via `launchd` (LaunchAgents).
- **Windows 10/11**: Supported via **Task Scheduler** (`schtasks`).
  - *Note:* Windows has limited support for signals (no `SIGUSR1/2` for flush/dump).
  - **Alpha Recommendation:** For the best experience during alpha, we recommend using **WSL2** (Ubuntu) instead of native Windows.

### Management Commands
- `mnemostroma config list`  — View all 70+ tunable parameters
- `mnemostroma logs --days 7` — Analyze memory growth and calibration
- `mnemostroma watch`        — Live terminal activity dashboard
- `mnemostroma tray`         — System tray indicator (optional)

---

## Model Setup

Models are downloaded automatically during `mnemostroma setup`.  
Required models (~300MB total):

- `multilingual-e5-small` (E5 int8, 384d) — session & content embedder
- `distilbert-ner` (DistilBERT int8) — HybridNER
- `tinybert-l2-v2` (TinyBERT, lazy) — reranker

---

## Logging

Mnemostroma writes local diagnostic logs to `logs.db` during alpha.  
**Logs never leave your machine.** No network calls.

To configure in `~/.mnemostroma/config.json`:
```json
"logging": { 
  "enabled": true,
  "mode": "safe" 
}
```
*Note: `safe` mode redacts sensitive content from logs, keeping only event types and metadata.*

---

## Stack

| Component                   | RAM        | Role                              |
| --------------------------- | ---------- | --------------------------------- |
| multilingual-e5-small INT8  | ~420MB     | Session & Content embedder (384d) |
| distilbert-ner INT8         | ~170MB     | HybridNER                         |
| TinyBERT-L-2-v2 INT8        | 8MB        | Cross-encoder reranking (lazy)    |
| ONNX Runtime + tokenizers   | 95MB       | Runtime                           |
| **Total working set (RSS)** | **~631MB** |                                   |

No torch. No transformers. No LangChain. No Docker. No Redis. No cloud.
Dependencies: `onnxruntime, tokenizers, numpy, lz4, aiosqlite`

---

## API surface (16 tools via MCP)

**Read (6):**
- `ctx_active()`: Current context snapshot (intent, variables, deadlines)
- `ctx_get(id)`: Retrieve specific session by ID
- `ctx_search(tags)`: Tag-based search (precise, multi-language)
- `ctx_semantic(query)`: Meaning-based search (MatrixSearch ANN, ~20ms)
- `ctx_anchors(type)`: Subconscious anchors (decisions, constraints, facts)
- `ctx_precision(type)`: Exact data (links, formulas, quotes)

**Extended (4):**
- `ctx_full(id)`: Full-text version from SQLite (for exact quoting)
- `ctx_bridge()`: Structured context handoff packet for next agent
- `ctx_urgent()`: Active deadlines and time-sensitive tasks
- `ctx_expire(id)`: Mark urgent task as completed/expired

**Content Branch (5):**
- `save_content(id, text)`: Versioned artifact save with `why_changed`
- `content_search(query)`: Semantic search over artifacts (code, docs)
- `content_get(id, version)`: Metadata retrieval for artifact
- `content_raw(id, version)`: Full source retrieval (expensive)
- `content_history(id)`: Version lineage and change log

**Admin (1):**
- `ctx_load(id)`: Force-load archived session from SQLite to RAM

---

## Connecting to LLM (MCP)

Mnemostroma is an MCP server. Add it to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "mnemostroma": {
      "command": "mnemostroma",
      "args": ["mcp"]
    }
  }
}
```

**Observer Principle:** You do not need to manually call "save_memory". The Mnemostroma Observer watches your conversation and handles everything in the background. You only call tools when you need to *remember* something from the past.

---

## How it compares

|                      | Mnemostroma            | MemGPT/Letta      | Zep               | Mem0          |
| -------------------- | ---------------------- | ----------------- | ----------------- | ------------- |
| Architecture         | RAM-first sidecar      | LLM-managed pages | Server + Postgres | Cloud API     |
| Retrieval latency    | **~20ms**              | ~200ms            | ~100ms            | **1.44s p95** |
| RAM overhead         | ~600MB                 | ~2GB+             | ~1GB+             | Cloud         |
| Offline              | **Yes**                | Partial           | No                | No            |
| GPU required         | **No**                 | Yes               | No                | Cloud         |
| Framework dependency | **None**               | LangChain         | LangChain         | SDK           |
| Agent writes memory  | **No (Observer)**      | Yes               | Yes               | Yes           |
| Memory dissolution   | **Gradual (5 layers)** | Binary evict      | TTL               | TTL           |
| Content versioning   | **Yes (diffs)**        | No                | No                | No            |

---

## Philosophy

Memory isn't storage.
Memory is knowing what to remember, when, and how much detail.

Mnemostroma doesn't give your agent a bigger context window.
It gives your agent an actual memory.

---

## License & Enterprise

**Mnemostroma Core is licensed under the FSL-1.1-MIT**.
Commercial restricted for 2 years (no SaaS competitors), then MIT.

**Mnemostroma Pro (Commercial)**
Cloud Sync, Subconscious Layer (personalized models), Shared Experience, and Team Context Import.

---

*Mnemostroma — the memory layer for AI agents*
*μνήμη + στρῶμα · offline · ~600MB · ~20ms · 303 tests*
