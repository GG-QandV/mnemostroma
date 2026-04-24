# Mnemostroma + claude.ai — Setup Guide

Connects Mnemostroma to claude.ai in two ways:

- **Tools**: Claude in claude.ai can call all 12 Mnemostroma MCP tools (ctx_semantic, ctx_search, etc.)
- **Context capture**: Mnemostroma observes the chat in real time — conversations are stored in memory automatically

Both require the daemon to be running. The connection module is independent — if it stops, the daemon continues.

---

## Prerequisites

- Mnemostroma daemon running: `mnemostroma on`
- Python environment with Mnemostroma installed
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installed and authenticated
- A domain managed in Cloudflare (for the public SSE endpoint)
- Chrome or Edge browser

---

## Step 1 — Install SSE dependencies

```bash
pip install mnemostroma[sse]
```

Installs `starlette` and `uvicorn`. The core daemon has no dependency on these.

---

## Step 2 — Start the SSE adapter

```bash
mnemostroma sse
```

Starts local servers:

| Port | Binding | Purpose |
|------|---------|---------|
| 8765 | 0.0.0.0 | MCP SSE endpoint for claude.ai (requires auth) |
| 8766 | 127.0.0.1 | Browser extension observe receiver (no auth) |
| 8767 | 127.0.0.1 | HTTPS passthrough proxy for Claude Code (requires `mnemostroma setup` for TLS cert) |

> Port 8767 is only started if TLS cert files exist (`~/.mnemostroma/passthrough-*.pem`). See [README passthrough proxy section](../README.md#claude-code--passthrough-proxy-observer-for-cli-sessions).

On first run, a token is generated:

```
~/.mnemostroma/sse_token
```

Print the token:

```bash
cat ~/.mnemostroma/sse_token
```

Keep this value — you will need it in Steps 4 and 5.

---

## Step 3 — Set up Cloudflare Tunnel

The SSE endpoint must be publicly reachable so claude.ai can connect to it.

### Create the tunnel (once)

```bash
cloudflared tunnel create mnemostroma
```

### Configure `~/.cloudflared/config.yml`

```yaml
tunnel: <tunnel-id>
credentials-file: /home/<user>/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: mnemo.yourdomain.com
    service: http://localhost:8765
  - service: http_status:404
```

Replace `<tunnel-id>` with the ID printed by `cloudflared tunnel create`.  
Replace `mnemo.yourdomain.com` with your chosen subdomain.

### Add DNS record

```bash
cloudflared tunnel route dns mnemostroma mnemo.yourdomain.com
```

### Run the tunnel

```bash
cloudflared tunnel run mnemostroma
```

To run as a persistent service (recommended):

```bash
sudo cloudflared service install
```

### Verify

```bash
curl https://mnemo.yourdomain.com/health
# → {"status": "ok", "daemon": "connected"}
```

---

## Step 4 — Configure claude.ai MCP

In claude.ai, open **Settings → Integrations → Add MCP Server** and enter:

| Field | Value |
|-------|-------|
| Type | SSE |
| URL | `https://mnemo.yourdomain.com/sse` |
| Authorization header | `Bearer <your-token>` |

Claude will now have access to all Mnemostroma tools in every conversation.

---

## Step 5 — Install the browser extension (context capture)

The extension watches the claude.ai DOM and forwards messages to the local observe receiver.

### Load the extension

1. Open `chrome://extensions`
2. Enable **Developer mode** (top right)
3. Click **Load unpacked**
4. Select the directory:
   ```
   /path/to/mnemostroma/src/mnemostroma/extension/
   ```

### Verify

The extension icon appears in the toolbar. Click it — popup shows:

```
Daemon  ● up
Queue   0
```

If the daemon is running and `mnemostroma sse` is active, status is green.

---

## Full startup sequence

```bash
mnemostroma on          # 1. Start memory daemon
mnemostroma sse         # 2. Start SSE adapter (keep running in a separate terminal)
cloudflared tunnel run mnemostroma   # 3. Start tunnel (or use systemd service)
```

After that: open claude.ai, start a conversation. The extension captures messages → daemon stores them in memory → Claude can retrieve them via MCP tools.

---

## Troubleshooting

**`/health` returns `{"daemon": "down"}`**  
→ Daemon not running. Run `mnemostroma on`.

**`/health` returns connection refused**  
→ SSE adapter not running. Run `mnemostroma sse`.

**claude.ai shows "MCP server unavailable"**  
→ Check tunnel is running: `curl https://mnemo.yourdomain.com/health`  
→ Check token matches: `cat ~/.mnemostroma/sse_token`

**Extension popup shows "daemon: down" but daemon is running**  
→ SSE adapter not running on port 8765. Run `mnemostroma sse`.

**Extension shows "daemon: up" but messages not appearing in memory**  
→ Check claude.ai DOM selector still works (Anthropic may have changed markup).  
→ Open DevTools on claude.ai → Console → look for `Mnemostroma:` log lines.

**Port 8765, 8766, or 8767 already in use**  
→ Find and stop the conflicting process:
```bash
lsof -i :8765
lsof -i :8766
lsof -i :8767
```

---

## Security notes

- The token in `~/.mnemostroma/sse_token` is the only auth for the public SSE endpoint. Keep it secret.
- The observe receiver (port 8766) is localhost-only and intentionally has no auth — it is not reachable through the tunnel.
- The token file is created with `chmod 600` automatically.
- To rotate the token: `rm ~/.mnemostroma/sse_token && mnemostroma sse` (generates a new one; update claude.ai config).
