# Release Notes — Mnemostroma v2.3.2

## Embedded MCP Adapters — No Separate Processes

Mnemostroma v2.3.2 eliminates the separate SSE and HTTP adapter processes. Both adapters now run **inside the daemon** — one process, lower RAM, no port conflicts on startup.

---

### Key Changes

#### 1. HTTP Adapter Embedded in Daemon

<img src="https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/src/extension/assets/head-circuit-256.png" width="96" align="right" />

- **Streamable HTTP (port 8768)** starts automatically with `mnemostroma on` — no separate terminal, no separate service.
- Direct `conductor.dispatch()` call — eliminates the IPC round-trip that the standalone adapter required.
- `mnemostroma http` command retained for standalone/debug mode with IPC fallback.
- `mnemostroma-http.service` removed.

#### 2. SSE Adapter Embedded in Daemon

- **SSE (port 8765)** starts automatically inside the daemon alongside HTTP.
- `mnemostroma sse` command retained for standalone/debug mode.
- `mnemostroma-sse.service` deprecated (no longer auto-installed).

#### 3. Port Conflict Protection

- Daemon checks `is_port_in_use()` before starting each embedded adapter.
- If a standalone adapter from an old installation is still running on that port — daemon logs a warning and skips starting that adapter. No crash, no silent failure.

#### 4. Config Controls

```json
// ~/.mnemostroma/config.json (optional overrides)
{
  "sse":  { "autostart": true, "port": 8765, "host": "127.0.0.1" },
  "http": { "autostart": true, "port": 8768, "host": "127.0.0.1" }
}
```

#### 5. MCP Client Configs Updated

All local clients switched from stdio to Streamable HTTP transport:

| Client      | Transport  | Config file                        |
| ----------- | ---------- | ---------------------------------- |
| Antigravity | HTTP :8768 | `~/.gemini/config/mcp_config.json` |
| VS Code     | HTTP :8768 | `~/.config/Code/User/mcp.json`     |
| Qoder       | HTTP :8768 | `~/.qoder/mcp.json`                |
| OpenCode    | HTTP :8768 | `~/.opencode/opencode.json`        |
| Cursor      | SSE :8765  | `~/.cursor/mcp.json`               |
| Claude Code | SSE :8765  | `~/.claude/mcp.json`               |

See `docs/mcp/MCP_CLIENT_CONFIGS.md` for full reference.

---

### Fixed

- **OpenCode auth error**: `type: "remote"` requires Streamable HTTP, was incorrectly pointed at SSE port 8765. Fixed → port 8768.
- **SSE adapter on Windows**: Removed `install_signal_handlers` and `NotificationOptions` patches that conflicted with daemon's ProactorEventLoop.

---

### Upgrade Instructions

See [UPGRADE.md](../UPGRADE.md) → *Upgrading to v2.3.2*

**TL;DR:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
systemctl --user stop mnemostroma-sse   # если был запущен
systemctl --user disable mnemostroma-sse
mnemostroma off && mnemostroma on
```

---

### Technical State

- **Tests**: 926 passing
- **RAM Footprint**: ~650 MB baseline (adapters embedded — ~65 MB saved vs previous)
- **Search Latency**: ~20ms semantic / ~5ms SQL
- **Regressions**: 0

---

**Generated:** 2026-06-01  
**Mnemostroma:** The offline-first memory layer for AI agents  
**v2.3.2** | 926 tests passing | 0 regressions | Embedded Adapters Release
