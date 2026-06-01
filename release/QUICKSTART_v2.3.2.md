# Quick Start — Mnemostroma v2.3.2

## Embedded MCP Adapters — One Process, Zero Setup

Starting from v2.3.2, SSE and Streamable HTTP adapters run **inside the daemon**. No separate terminals, no separate services — just `mnemostroma on`.

### What's new in v2.3.2

- **Streamable HTTP embedded (port 8768)**: primary transport for VS Code, Antigravity, OpenCode, Qoder — starts with daemon automatically.
- **SSE embedded (port 8765)**: transport for Cursor, Claude Code, Grok, Perplexity — starts with daemon automatically.
- **Port conflict protection**: if an old standalone adapter is running, daemon warns and skips — no crash.
- **OpenCode fix**: transport corrected to Streamable HTTP (was incorrectly SSE).
- **Beta label removed** from CLI and docs.

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

**Upgrade from v2.3.x:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
systemctl --user stop mnemostroma-sse    # если был запущен отдельно
systemctl --user disable mnemostroma-sse
mnemostroma off && mnemostroma on
```

---

### Ports after `mnemostroma on`

| Port | Transport | Clients |
|------|-----------|---------|
| `8768` | Streamable HTTP | VS Code, Antigravity, OpenCode, Qoder |
| `8765` | SSE | Cursor, Claude Code, Grok, Perplexity |
| `8766` | HTTP/POST | Browser Extension (localhost only) |
| `8767` | HTTPS Proxy | Claude Code passthrough |
| `8769` | MCP OAuth Adapter | Remote tunnel (Serveo/Cloudflare) |

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

---

### 📢 Browser Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select: `~/.mnemostroma/extension/`

---

### Technical State (v2.3.2)

<details>
<summary><b>Benchmarks & Stability</b></summary>

- **Tests**: 831/831 passed (100% Green).
- **RAM Footprint**: ~650 MB baseline (~65 MB saved vs v2.3.1 — adapters embedded).
- **Search Latency**: ~20ms (Semantic) / ~5ms (SQL).

</details>

<details>
<summary><b>Security & Ports</b></summary>

- **Authorization**: Bearer token для HTTP (:8768) и SSE (:8765).
- **Isolation**: Observer (:8766) — `127.0.0.1` only.
- **Credentials**: `token_urlsafe(32)`, `chmod 0600`.

</details>

---

### License

**FSL-1.1-MIT** — для личного использования бесплатно навсегда.

---

**Generated:** 2026-06-01  
**v2.3.2** | 831 tests green | [Full Release Notes](./RELEASE_NOTES_v2.3.2.md)
