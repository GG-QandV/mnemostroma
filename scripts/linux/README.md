# Mnemostroma Daemon Installation — Linux (systemd)

Self-hosted systemd user units for Mnemostroma daemon.

## Files

- **mnemostroma-daemon.service** — Main daemon process (Observer + Memory + Storage)
- **mnemostroma-sse.service** — SSE Adapter (MCP + Observe + Passthrough Proxy ports 8765-8767)
- **mnemostroma-proxy.service** — HTTP Proxy (legacy, deprecated in favor of sse)
- **mnemostroma-watchdog.service** — Health monitor
- **install.sh** — Setup script (copies units and enables them)

## Installation

```bash
bash scripts/linux/install.sh
```

Or with a specific username (if installing for another user):
```bash
bash scripts/linux/install.sh username
```

## Management

```bash
# Status
systemctl --user status mnemostroma-daemon

# Start/stop
systemctl --user start mnemostroma-daemon
systemctl --user stop mnemostroma-daemon

# Enable/disable on boot
systemctl --user enable mnemostroma-daemon
systemctl --user disable mnemostroma-daemon

# Logs
journalctl --user -u mnemostroma-daemon -f
journalctl --user -u mnemostroma-sse -f
journalctl --user -u mnemostroma-watchdog -f
```

## Architecture

| Component | Port | Purpose |
|-----------|------|---------|
| **daemon** | socket | Core memory system (Observer, Consolidation, Dissolver) |
| **sse** | 8765 | MCP Server (SSE transport for claude.ai) |
| **sse** | 8766 | Observe receiver (localhost, browser extension) |
| **sse** | 8767 | Passthrough proxy (HTTPS, routes Claude Code API traffic) |
| **watchdog** | — | Health checks, heartbeat monitoring |

## Details

- User-level units (no sudo required, runs as current user only)
- Socket location: `~/.mnemostroma/daemon.sock`
- Logs: journalctl (no separate log file)
- Restart policy: always + watchdog health checks
