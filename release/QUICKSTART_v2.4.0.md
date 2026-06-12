# Quick Start — Mnemostroma v2.4.0

## Embedded MCP Adapters — One Process, Zero Setup

Starting from v2.4.0, SSE and Streamable HTTP adapters run **inside the daemon**. No separate terminals, no separate services — just `mnemostroma on`.

### What's new in v2.4.0

- **Streamable HTTP embedded (port 8768)**: primary transport for VS Code, Antigravity, OpenCode, Qoder — starts with daemon automatically.
- **SSE embedded (port 8765)**: transport for Cursor, Claude Code, Grok, Perplexity — starts with daemon automatically.
- **5 local clients migrated** from stdio to Streamable HTTP transport (Antigravity, VS Code, Qoder, OpenCode — HTTP :8768; Cursor, Claude Code — SSE :8765).
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
systemctl --user disable --now mnemostroma-http.service 2>/dev/null || true
mnemostroma off && mnemostroma on
```

---

### Ports after `mnemostroma on`

| Port | Transport | Clients | Access |
|------|-----------|---------|--------|
| `8768` | Streamable HTTP | VS Code, Antigravity, OpenCode, Qoder | Local |
| `8765` | SSE | Cursor, Claude Code | Local |
| `8766` | HTTP/POST | Browser Extension | localhost only |
| `8767` | HTTPS Proxy | Claude Code passthrough | Local |
| `8769` | MCP OAuth Adapter | Remote: Perplexity, Grok, Claude.ai, ChatGPT | Tunnel (Serveo/Cloudflare) |

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

**Remote clients (tunnel)** — Perplexity, Grok, Claude.ai, ChatGPT:

See full guides:
- `docs/mcp/serveo_perplexity_none_auth_guide.md` — Perplexity via Serveo + no auth
- `docs/tunnel/TUNNEL_SETUP.md` — Claude.ai, ChatGPT OAuth setup
- `docs/mcp/mcp_oauth_adapter/guide.md` — OAuth adapter reference

---

### 📢 Browser Extension

1. Open `chrome://extensions`
2. Enable **Developer mode**
3. Click **Load unpacked**
4. Select: `~/.mnemostroma/extension/` (Linux/macOS) or `%USERPROFILE%\.mnemostroma\extension` (Windows)

---

### Technical State (v2.4.0)

<details>
<summary><b>Benchmarks & Stability</b></summary>

- **Tests**: 926/926 passed (100% Green).
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
**v2.4.0** | 926 tests green | [Full Release Notes](./RELEASE_NOTES_v2.4.0.md)
