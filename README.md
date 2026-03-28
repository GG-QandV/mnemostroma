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

A dual-stream async pipeline (Observer + Content) backed by three memory layers,
HNSWlib ANN search, ONNX INT8 inference, and SQLite WAL cold storage —
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

## Stack

| Component                     | RAM        | Role                              |
| ----------------------------- | ---------- | --------------------------------- |
| EmbeddingGemma-300M INT8      | 52MB       | Session vectorization (512d)      |
| BGE-M3 INT8                   | 145MB      | Content vectorization (lazy load) |
| GLiNER-small-v2.1 INT8        | 42MB       | Zero-shot NER                     |
| TinyBERT-L-2-v2 INT8          | 8MB        | Cross-encoder reranking           |
| ONNX Runtime + tokenizers     | 95MB       | Runtime                           |
| **Total models**              | **342MB**  |                                   |
| + Session data (200 sessions) | ~260MB     |                                   |
| **Total working set**         | **~600MB** |                                   |

No torch. No transformers. No LangChain. No Docker. No Redis. No cloud.

Dependencies: `onnxruntime, tokenizers, numpy, hnswlib, lz4`

---

## Components

| Component          | Role                                          | Analogy                              |
| ------------------ | --------------------------------------------- | ------------------------------------ |
| **Observer**       | Builds semantic context from agent I/O        | Auditory system                      |
| **Dissolver**      | Gradually reduces memory resolution over time | Forgetting curve                     |
| **Tuner**          | Detects conflicts, drift, stale anchors       | Piano tuner — listens for dissonance |
| **Conductor**      | Bootstrap, event loop, health, RAM budget     | Orchestra conductor                  |
| **Session Bridge** | Context handoff between sessions              | Waking up and remembering yesterday  |

---

## API surface (18 tools via MCP)

**Read:**
`ctx.active()` · `ctx.get()` · `ctx.search()` · `ctx.semantic()` · `ctx.anchors()` · `ctx.precision()` · `ctx.full()` · `ctx.bridge()` · `ctx.urgent()` · `ctx.expire()`

**Write:**
`ctx.save()` · `ctx.update()` · `ctx.flag()` · `content.save()` · `content.tag()`

**Admin:**
`ctx.sync()` · `ctx.load()` · `ctx.status()` · `ctx.growth()` · `ctx.pulse()` · `ctx.configure()`

---

## Deployment

```bash
# Embedded (Python agent)
from mnemostroma import ctx, content
bridge = ctx.active()  # system starts automatically

# Daemon (IDE, terminal agents)
ctx daemon start       # one daemon per machine
ctx status             # dashboard

# CLI
ctx search "#JWT"
ctx semantic "authorization flow"
ctx bridge
```

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

## Roadmap

| Phase | What                                                                  | Status         |
| ----- | --------------------------------------------------------------------- | -------------- |
| v1.x  | MVP: Observer + Session Index + Dissolver + Tuner + Content + MCP API | 🔄 In progress |
| v1.3  | Urgency policy + principle protection                                 | 📋 Specified   |
| v1.5  | Implicit feedback + Experience Layer + clustering                     | 📋 Specified   |
| v2.0  | Explicit feedback + adaptive score weights                            | 📋 Planned     |
| v3.0  | Hypómnema Strōma — subconscious layer (~11MB personalized models)     | 📋 Planned     |

---

## Philosophy

Memory isn't storage.
Memory is knowing what to remember, when, and how much detail.

Mnemostroma doesn't give your agent a bigger context window.
It gives your agent an actual memory.

---

## License & Enterprise

**Mnemostroma Core is licensed under the FSL-1.1-MIT (Functional Source License)**.
This means you are completely free to use, modify, and integrate Mnemostroma into your internal projects, products, and agents.

The ONLY restriction is that you **cannot provide Mnemostroma itself as a competing Commercial SaaS product**. After 2 years, the license automatically transitions to a standard MIT License.

**Mnemostroma Pro (Commercial)**
Features such as **Cloud Sync**, **Subconscious Layer (Hypómnema Strōma)**, **Shared Experience**, and **Team Context Import** are developed and maintained in a separate private repository and are available under a commercial enterprise license.

For more details, see the `LICENSE` file.

*Mnemostroma — the memory layer for AI agents*
*μνήμη + στρῶμα · offline · ~600MB · ~20ms · no GPU*
