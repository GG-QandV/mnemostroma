# Release Notes — Mnemostroma v2.5.1

## Gateway Provider Dispatch

Mnemostroma v2.5.1 introduces a complete Gateway Provider Dispatch pipeline — an OpenAI-compatible, non-streaming Chat Completions endpoint with memory injection, observation, admission control, and response normalization. Also includes the HTTP Read Adapter (v2.5.0) and embedded Streamable HTTP MCP.

---

### Key Changes

#### 1. Gateway Provider Dispatch (R6b–R19)

- **Provider Transport**: `HttpxProviderTransport` — production HTTP transport with configurable timeouts, retries, and TLS verification.
- **Memory Injection**: `MemoryInjector` Protocol — injects `<memorycontext>` into every provider request (in `active` mode).
- **Observation**: `CompletionObserver` Protocol — captures provider responses into memory, with `ObservationTaskRegistry` for lifecycle drain.
- **Completion Normalization**: `normalize_completion` — Gateway-owned IDs, consistent response shape across providers.
- **Admission Control**: `DispatchAdmission` — bounds concurrent dispatches and memory requests (`max_concurrent_dispatches`, `max_concurrent_memory_requests`).
- **Request Limits**: `validate_chat_request` — enforces 64 messages max, 1 MiB body cap.
- **Cancellation Propagation**: `CancelledError` guards — permits release on cancel, clean dispatch abort.
- **Provider Credential Resolution**: `EnvironmentCredentialResolver` — token validation, `ProviderCredentialResolver` Protocol.
- **Provider URL Egress Policy**: `validate_provider_base_url` — blocks redirects (`follow_redirects=False`), invalid URLs → 502.
- **Content-Safe Metrics**: `GatewayMetrics` — 12 fixed counters, 5 latency aggregates, no PII.
- **ConductorProxy Adapters**: `ConductorProxyMemoryInjector`, `ConductorProxyCompletionObserver` — wire Gateway into daemon memory.

#### 2. HTTP Read Adapter (v2.5.0)

- Ultra-low latency REST endpoint on port `8762` for CLI/scripts/browsers.
- Direct memory read access without MCP protocol overhead.
- Full `ctx_semantic`, `ctx_anchors`, `ctx_search`, `ctx_recent`, `ctx_bridge` via HTTP GET.

#### 3. Embedded Streamable HTTP MCP

- Streamable HTTP transport (port `8768`) runs inside the daemon — no separate process.
- Primary transport for VS Code, Antigravity, OpenCode, Qoder.
- Bearer token auth, auto-generated on daemon start.

#### 4. Config & Ports

| Port   | Service             | Description                        |
| ------ | ------------------- | ---------------------------------- |
| `8762` | HTTP Read Adapter   | REST endpoint for CLI/scripts      |
| `8765` | SSE MCP             | Cursor, Claude Code                |
| `8768` | Streamable HTTP MCP | VS Code, Antigravity, OpenCode     |
| `8780` | Gateway (basic)     | OpenAI-compatible Chat Completions |
| `8781` | Gateway (full)      | + memory injection & observation   |

---

### Upgrade Instructions

See [UPGRADE.md](../UPGRADE.md) → *Upgrading to v2.5.1*

**TL;DR:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma off && mnemostroma on
```

---

### Technical State

- **Tests**: 1477 passing (+217 gateway & integration tests over v2.4.0)
- **RAM Footprint**: ~650 MB baseline
- **Search Latency**: ~20ms semantic / ~5ms SQL
- **Gateway Latency**: ~50ms overhead (memory inject + observe)
- **Regressions**: 0

---

**Generated:** 2026-07-11  
**Mnemostroma:** The offline-first memory layer for AI agents  
**v2.5.1** | 1477 tests passing | 0 regressions | Gateway Provider Dispatch Release
