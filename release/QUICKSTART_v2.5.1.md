# Quick Start — Mnemostroma v2.5.1

## Gateway Provider Dispatch + HTTP Read Adapter

v2.5.1 introduces the Gateway Provider Dispatch — an OpenAI-compatible Chat Completions endpoint with memory injection and observation. Also includes the HTTP Read Adapter for ultra-low latency memory access.

### What's new in v2.5.1

- **Gateway Provider Dispatch (ports 8780/8781)**: OpenAI-compatible non-streaming Chat Completions. `:8780` = basic dispatch, `:8781` = +memory injection & observation. 
- **HTTP Read Adapter (port 8762)**: REST endpoint for CLI/scripts/browsers — `curl http://127.0.0.1:8762/semantic?q=...`
- **Streamable HTTP MCP (port 8768)**: primary transport for VS Code, Antigravity, OpenCode — runs inside daemon.
- **446 gateway tests** added, 1477 total.

---

### Installation & Setup

**Option A: Linux/macOS**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/windows/install-daemon.ps1 -OutFile install-daemon.ps1; .\install-daemon.ps1"
```

**Upgrade from v2.4.x:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma off && mnemostroma on
```

---

### Ports after `mnemostroma on`

| Port   | Transport               | Clients                                      | Access         |
| ------ | ----------------------- | -------------------------------------------- | -------------- |
| `8762` | HTTP/REST               | CLI, scripts, browsers                       | Local          |
| `8765` | SSE                     | Cursor, Claude Code                          | Local          |
| `8766` | HTTP/POST               | Browser Extension                            | localhost only |
| `8767` | HTTPS Proxy             | Claude Code passthrough                      | Local          |
| `8768` | Streamable HTTP         | VS Code, Antigravity, OpenCode, Qoder        | Local          |
| `8769` | MCP OAuth Adapter       | Remote: Perplexity, Grok, Claude.ai, ChatGPT | Tunnel         |
| `8780` | OpenAI Chat Completions | Any OpenAI client (basic)                    | Local          |
| `8781` | OpenAI Chat Completions | Any OpenAI client (memory)                   | Local          |

Token: `cat ~/.mnemostroma/sse_token`

---

### Connect your IDE

Full reference: `docs/mcp/MCP_CLIENT_CONFIGS.md`

**Antigravity / VS Code / Qoder** (`serverUrl` или `type: http`):

```json
"mnemostroma": {
  "serverUrl": "http://127.0.0.1:8768/mcp",
  "headers": { "Authorization": "Bearer <TOKEN>" }
}
```

**Cursor / Claude Code** (`type: sse`):

```json
"mnemostroma": {
  "type": "sse",
  "url": "http://127.0.0.1:8765/sse?token=<TOKEN>"
}
```

**OpenCode** (`type: remote`):

```json
"mnemostroma": {
  "type": "remote",
  "url": "http://127.0.0.1:8768/mcp?token=<TOKEN>",
  "enabled": true
}
```

**Use Gateway as OpenAI provider:**

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://127.0.0.1:8781/v1",
    api_key="any"
)
response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}]
)
```

---

### 📢 Browser Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select: `~/.mnemostroma/extension/` (Linux/macOS) or `%USERPROFILE%\.mnemostroma\extension` (Windows)

---

### Technical State (v2.5.1)

<details>
<summary><b>Tests & Stability</b></summary>

- **Tests**: 1477/1477 passed (100% Green).
- **RAM Footprint**: ~650 MB baseline.
- **Search Latency**: ~20ms (Semantic) / ~5ms (SQL).
- **Gateway Overhead**: ~50ms per request (memory inject + observe).

</details>

<details>
<summary><b>Gateway Providers</b></summary>

- **Built-in**: `openai/gpt-4o`, `openai/gpt-4o-mini`, `anthropic/claude-sonnet-4-20250514` (via OpenAI-compatible wrapper).
- **Custom**: any `base_url` + `api_key` via config.
- **Auth**: `ENV` provider — reads `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, etc.
- **Safety**: redirects blocked (→ 502), body capped at 1 MiB, max 64 messages.

</details>

<details>
<summary><b>Security & Ports</b></summary>

- **Authorization**: Bearer token for HTTP (:8768) and SSE (:8765).
- **Isolation**: Observer (:8766) — `127.0.0.1` only.
- **Gateway**: `127.0.0.1` only, no auth (local trust).
- **Credentials**: `token_urlsafe(32)`, `chmod 0600`.

</details>

---

### License

**FSL-1.1-MIT** — для личного использования бесплатно навсегда.

---

**Generated:** 2026-07-11  
**v2.5.1** | 1477 tests green | [Full Release Notes](./RELEASE_NOTES_v2.5.1.md)
