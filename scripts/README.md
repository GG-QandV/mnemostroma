# Mnemostroma Daemon Installation Scripts

Cross-platform daemon setup for Mnemostroma (Observer + Memory + Storage).

## Quick Start

**Linux / macOS:**
```bash
bash scripts/install-daemon.sh
```

**Windows (PowerShell as Administrator):**
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\scripts\windows\install-daemon.ps1
```

## What This Does

1. Detects your OS
2. Installs daemon as system service (systemd/launchd/Task Scheduler)
3. Enables auto-start on login
4. Starts daemon immediately
5. Confirms socket is ready for clients

## Directory Structure

```
scripts/
├── install-daemon.sh          # Universal entry point (auto-detects OS)
├── README.md                  # This file
│
├── linux/                      → [Linux (systemd) Installation](./linux/README.md)
│   ├── install.sh             # systemd setup
│   ├── mnemostroma-daemon.service
│   ├── mnemostroma-proxy.service
│   ├── mnemostroma-watchdog.service
│   └── README.md
│
├── macos/                      → [macOS (launchd) Installation](./macos/README.md)
│   ├── install.sh             # launchd setup
│   ├── com.mnemostroma.daemon.plist
│   └── README.md
│
└── windows/                    → [Windows (Task Scheduler) Installation](./windows/README.md)
    ├── install-daemon.ps1     # Task Scheduler setup
    └── README.md
```

## Architecture

```
┌─────────────────────────────────────────────┐
│  Client (VS Code, Claude Code, Cursor)      │
│  └─ spawns adapter process on startup       │
└──────────────┬──────────────────────────────┘
               │
               │ stdio/socket
               ↓
    ┌──────────────────────┐
    │  Adapter (~70 MB)    │
    │  (ephemeral)         │
    └──────────┬───────────┘
               │
               │ daemon.sock
               ↓
    ┌──────────────────────┐
    │  Daemon (~630 MB)    │
    │  (persistent)        │
    │  - Observer          │
    │  - Memory layers     │
    │  - Storage (SQLite)  │
    │  - MatrixSearch ANN  │
    └──────────────────────┘
```

**Important:** Daemon must be running before any client connects.

## Uninstallation

**Linux:**
```bash
systemctl --user disable mnemostroma-daemon
systemctl --user disable mnemostroma-proxy
systemctl --user disable mnemostroma-watchdog
rm ~/.config/systemd/user/mnemostroma-*.service
systemctl --user daemon-reload
```

**macOS:**
```bash
launchctl unload ~/Library/LaunchAgents/com.mnemostroma.daemon.plist
rm ~/Library/LaunchAgents/com.mnemostroma.daemon.plist
```

**Windows (PowerShell):**
```powershell
Stop-ScheduledTask -TaskName "Mnemostroma Daemon"
Unregister-ScheduledTask -TaskName "Mnemostroma Daemon" -Confirm:$false
```

## Troubleshooting

**Daemon won't start:**
```bash
# Linux
journalctl --user -u mnemostroma-daemon -f

# macOS
tail -f ~/.mnemostroma/daemon.log
tail -f ~/.mnemostroma/daemon.err

# Windows (PowerShell)
$task = Get-ScheduledTask -TaskName "Mnemostroma Daemon"
$task.State
Get-ScheduledTaskInfo -TaskName "Mnemostroma Daemon"
```

**Port conflicts:**
Daemon uses Unix domain socket (`~/.mnemostroma/daemon.sock`), not TCP. No port conflicts possible.

**Check daemon status:**
```bash
mnemostroma status
```

## Documentation

- [Linux (systemd)](./linux/README.md)
- [macOS (launchd)](./macos/README.md)
- [Windows (Task Scheduler)](./windows/README.md)
