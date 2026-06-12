# MNEMOSTROMA SYSTEM ASSESSMENT (v2.4.0)

## Architecture, Port Allocation & Resource Footprint

> **Assessment note**: v2.4.0 embeds SSE and HTTP MCP adapters inside the daemon process — eliminating two separate processes (~65 MB RAM saved). Port conflict protection added. 926 tests passing.

---

### 1. Core Components, RAM Allocations & Active Listeners

| Component                     | Role                                              | RAM Baseline | RAM Peak    | Active Port / Binding                                           |
| ----------------------------- | ------------------------------------------------- | ------------ | ----------- | --------------------------------------------------------------- |
| **Daemon (conductor)**        | Core orchestrator, memory, routing                | ~480 MB      | ~650 MB     | Unix Socket / Named Pipe (IPC)                                  |
| **SSE Adapter** *(embedded)*  | SSE MCP router — внутри daemon                    | 0 MB extra   | 0 MB extra  | Port `8765` `127.0.0.1` (token-auth) / `8766` (local, no-auth)  |
| **HTTP Adapter** *(embedded)* | Streamable HTTP MCP router — внутри daemon        | 0 MB extra   | 0 MB extra  | Port `8768` `127.0.0.1` (token-auth)                            |
| **TLS Passthrough Proxy**     | HTTPS tunnel proxy для CLI клиентов               | ~10 MB       | ~25 MB      | Port `8767` `127.0.0.1` (self-signed TLS)                       |
| **MCP OAuth Adapter**         | Remote MCP + OAuth 2.1 + Cloudflare/Serveo tunnel | ~20 MB       | ~40 MB      | Port `8769` `127.0.0.1`                                         |
| **Observer**                  | Browser extension DOM capture                     | ~45 MB       | ~90 MB      | Streams to port `8766` (localhost)                              |
| **IPC Server**                | Socket-based tool dispatch                        | ~5 MB        | ~15 MB      | Unix Socket `~/.mnemostroma/daemon.sock` / Named Pipe (Windows) |
| **Dreamer**                   | Background distillation & consolidation           | ~30 MB       | ~60 MB      | Internal task                                                   |
| **Matrix Search** (ANN/Numpy) | Semantic + Temporal retrieval                     | ~55 MB       | ~90 MB      | 384-dim ONNX, ~20ms latency                                     |
| **Memory Strata**             | 5-layer storage orchestration                     | ~40 MB       | ~70 MB      | RAM Hot → Ledger → Experience → Subconscious → Archive          |
| **Persistence Layer**         | SQLite WAL                                        | ~25 MB       | ~50 MB      | `~/.mnemostroma/mnemostroma.db`                                 |
| **Models (Zoo)**              | Neural networks (INT8 ONNX)                       | ~100 MB      | ~185 MB     | Shared sessions, lazy load                                      |
| **TOTAL BASELINE**            |                                                   | **~650 MB**  |             |                                                                 |
| **TOTAL PEAK**                |                                                   |              | **~750 MB** | Within hard limit                                               |

---

### 2. Network Interface Allocation

| Port   | Binding     | Protocol  | Auth          | Clients                                | Purpose                                  |
| ------ | ----------- | --------- | ------------- | -------------------------------------- | ---------------------------------------- |
| `8768` | `127.0.0.1` | HTTP      | Bearer Token  | VS Code, Antigravity, OpenCode, Qoder  | Streamable HTTP MCP (основной транспорт) |
| `8765` | `127.0.0.1` | HTTP/SSE  | Bearer Token  | Cursor, Claude Code                    | SSE MCP transport (local)               |
| `8766` | `127.0.0.1` | HTTP/POST | None (local)  | Browser Extension                      | DOM capture stream                       |
| `8767` | `127.0.0.1` | HTTPS     | None (local)  | Claude Code (CLI)                      | TLS passthrough proxy                    |
| `8769` | `127.0.0.1` | HTTP      | OAuth / Token | Remote: Perplexity, Grok, Claude.ai, ChatGPT | MCP OAuth Adapter + tunnel          |

---

### 3. MCP Client Transport Map

| Client          | Config file                                | Transport       | Port |
| --------------- | ------------------------------------------ | --------------- | ---- |
| Antigravity     | `~/.gemini/config/mcp_config.json`         | Streamable HTTP | 8768 |
| Antigravity IDE | `~/.gemini/antigravity-ide/mcp_config.json`| Streamable HTTP | 8768 |
| VS Code         | `~/.config/Code/User/mcp.json`             | Streamable HTTP | 8768 |
| Qoder           | `~/.qoder/mcp.json`                        | Streamable HTTP | 8768 |
| OpenCode        | `~/.opencode/opencode.json`                | Streamable HTTP | 8768 |
| Workspace       | `Project_mnemostroma/.mcp.json`            | Streamable HTTP | 8768 |
| Cursor          | `~/.cursor/mcp.json`                       | SSE             | 8765 |
| Claude Code     | `~/.claude/mcp.json`                       | SSE             | 8765 |

Full reference: `docs/mcp/MCP_CLIENT_CONFIGS.md`

---

### 4. Neural Models & Embedding Pipeline

| Model                     | Size (INT8) | Dimensions | Latency                | Role                             |
| ------------------------- | ----------- | ---------- | ---------------------- | -------------------------------- |
| **multilingual-e5-small** | 117 MB      | 384d       | ~15ms cold / ~2ms warm | Semantic search & embedding      |
| **distilbert-ner**        | 60 MB       | —          | ~8ms                   | NER, precision extraction        |
| **tinybert-l2-v2**        | 7 MB        | —          | ~5ms                   | Cross-encoder reranking (lazy)   |
| **TOTAL**                 | **184 MB**  |            |                        | Downloaded once, shared sessions |

---

### 5. Operational Parameters

| Parameter           | Value          | Notes                                         |
| ------------------- | -------------- | --------------------------------------------- |
| **RAM Hard Limit**  | 750 MB         | Evicts cold vectors on breach                 |
| **Tests**           | 926/926 ✅      | 100% Green                                    |
| **Regressions**     | 0              |                                               |
| **Token security**  | `0600` (POSIX) | `token_urlsafe(32)`, auto-locked on creation  |
| **Search latency**  | ~20ms semantic | ~5ms SQL exact                                |
| **Context handoff** | < 50ms         | AutoBridgeWorker precompute                   |
| **Backup interval** | 3h             | Incremental SQLite backup                     |
| **Windows support** | Win 10/11      | Task Scheduler, Named Pipe, ProactorEventLoop |

---

**Generated:** 2026-06-01  
**Mnemostroma:** The offline-first memory layer for AI agents  
**v2.4.0** | 926 tests passing | 0 regressions | Embedded Adapters Release
