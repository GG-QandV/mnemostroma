# Mnemostroma Daemon Installation — macOS (launchd)

Self-hosted launchd LaunchAgent for Mnemostroma daemon.

## Files

- **com.mnemostroma.daemon.plist** — LaunchAgent configuration for the main daemon process.
- **install.sh** — Setup script (installs and starts the agent).

## Installation

```bash
# Recommended: Use the universal installer
bash scripts/install-daemon.sh
```

Or run the macOS-specific installer directly:
```bash
bash scripts/macos/install.sh
```

## Management

```bash
# Start
launchctl start com.mnemostroma.daemon

# Stop
launchctl stop com.mnemostroma.daemon

# Unload (disable on login)
launchctl unload ~/Library/LaunchAgents/com.mnemostroma.daemon.plist

# Logs
tail -f ~/.mnemostroma/daemon.log
tail -f ~/.mnemostroma/daemon.err
```

## Details

- User-level agent (runs as current user)
- Socket location: `~/.mnemostroma/daemon.sock`
- KeepAlive: true (restarts if terminated)
- RunAtLoad: true (auto-starts on login)
