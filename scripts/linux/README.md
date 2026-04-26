# Mnemostroma Daemon Installation — Linux (systemd)

Self-hosted systemd user units for Mnemostroma daemon.

## Files

- **mnemostroma-daemon.service** — Main daemon process (Observer + Memory + Storage)
- **mnemostroma-proxy.service** — HTTPS passthrough proxy & SSE Adapter (Ports 8765-8767)
- **mnemostroma-watchdog.service** — Health monitor & auto-recovery
- **mnemostroma-ui.service** — System Tray UI (RAM/Status visualization)
- **install.sh** — Setup script (copies units and enables them)

## Installation

```bash
# Recommended: Use the universal installer
bash scripts/install-daemon.sh
```

Or run the Linux-specific installer directly:
```bash
bash scripts/linux/install.sh
```

## Management

```bash
# Status of all services
mnemostroma status

# Logs
mnemo-logs
# or
journalctl --user -u mnemostroma-daemon -f

# Restart
mnemo-restart
```

## Architecture

| Component | Port | Purpose |
|-----------|------|---------|
| **daemon** | socket | Core memory system (Observer, Consolidation, Dissolver) |
| **proxy** | 8765 | MCP Server (SSE transport for claude.ai) |
| **proxy** | 8766 | Observe receiver (localhost, browser extension) |
| **proxy** | 8767 | Passthrough proxy (HTTPS, routes Claude Code API traffic) |
| **watchdog** | — | Health checks, heartbeat monitoring |
| **ui** | — | System tray icon and status window |

## Details

- User-level units (no sudo required, runs as current user only)
- Socket location: `~/.mnemostroma/daemon.sock`
- Integration: Automatically adds aliases (`mnemo-logs`, `mnemo-restart`) to your `.bashrc` or `.zshrc`.
