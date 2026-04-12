# Mnemostroma Daemon Installation — Linux (systemd)

Self-hosted systemd user units for Mnemostroma daemon.

## Files

- **mnemostroma-daemon.service** — Main daemon process
- **mnemostroma-proxy.service** — HTTPS passthrough proxy (optional, for Claude Code)
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
journalctl --user -u mnemostroma-proxy -f
journalctl --user -u mnemostroma-watchdog -f
```

## Details

- User-level units (no sudo required, runs as current user only)
- Socket location: `~/.mnemostroma/daemon.sock`
- Logs: journalctl (no separate log file)
- Restart policy: always + watchdog health checks
