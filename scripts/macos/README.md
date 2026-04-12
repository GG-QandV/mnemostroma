# Mnemostroma Daemon Installation — macOS (launchd)

Self-hosted launchd LaunchAgent for Mnemostroma daemon.

## Files

- **com.mnemostroma.daemon.plist** — LaunchAgent configuration
- **install.sh** — Setup script (installs and starts the agent)

## Installation

```bash
bash scripts/macos/install.sh
```

This will:
1. Detect your Python venv at `~/.mnemostroma/venv/bin/python3`
2. Copy the plist file to `~/Library/LaunchAgents/`
3. Load the agent with `launchctl`
4. Start the daemon

## Management

```bash
# Start
launchctl start com.mnemostroma.daemon

# Stop
launchctl stop com.mnemostroma.daemon

# Unload (disable on login)
launchctl unload ~/Library/LaunchAgents/com.mnemostroma.daemon.plist

# Reload (after edits to plist)
launchctl unload ~/Library/LaunchAgents/com.mnemostroma.daemon.plist
launchctl load ~/Library/LaunchAgents/com.mnemostroma.daemon.plist

# Logs
tail -f ~/.mnemostroma/daemon.log
tail -f ~/.mnemostroma/daemon.err
```

## Details

- User-level agent (runs as current user)
- Socket location: `~/.mnemostroma/daemon.sock`
- Logs: separate files (daemon.log and daemon.err)
- KeepAlive: true (restarts if terminated)
- RunAtLoad: true (auto-starts on login)
