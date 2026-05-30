# Mnemostroma Tray & Browser Extension Guide

## System Tray (`mnemostroma tray`)

The tray icon lives in your system notification area (top-right on Linux/macOS, bottom-right on Windows). It gives you one-click access to Mnemostroma controls without opening a terminal.

### Starting the tray

```bash
mnemostroma tray
```

On Linux, the tray also starts automatically via `mnemostroma-ui.service` (systemd).

### Tray menu

| Menu item | What it does |
|---|---|
| **Daemon: RUNNING / STOPPED** | Shows daemon status (not clickable) |
| **Open Dashboard** | Opens `mnemostroma watch` terminal dashboard |
| **Tunnel →** | Submenu with tunnel controls (see below) |
| **Hard RAM Reset (Emergency)** | Kills all Mnemostroma processes and clears RAM without touching your databases |
| **Quit** | Stops the tray (daemon keeps running in background) |

### Tunnel submenu

| Item | Action |
|---|---|
| **Tunnel: Active / Starting… / Off** | Status line, updates every 5s |
| **▶ Start Tunnel** | Starts Cloudflare tunnel + OAuth adapter |
| **■ Stop Tunnel** | Stops the tunnel gracefully |
| **↺ Restart Tunnel** | Force kill → 1.5s pause → restart |
| **✕ Force Kill (Emergency)** | Kills cloudflared immediately |

### Tray icon behaviour

- **Icon visible** — tray is running
- **No icon** — tray not started or crashed (run `mnemostroma tray` again)

---

## Browser Extension

The extension feeds your web chat conversations (Claude.ai, ChatGPT, etc.) into Mnemostroma's memory automatically. Install once, forget about it.

### Installation

Follow the [Browser Extension Installation Guide](./src/extension/docs/INSTALL.md).

### Icon badges

The extension icon in your browser toolbar shows connectivity status:

| Badge | Meaning |
|---|---|
| **Green badge / Clean** | Daemon is running, capture is enabled, last POST succeeded |
| **Yellow badge / `!`** | Daemon is running but capture is paused, site is disabled, or last POST failed |
| **Red badge / `X`** | Cannot connect to daemon. Run `mnemostroma on` to start it |

### Tunnel ring

A circular ring around the extension icon shows tunnel status independently:

| Ring | Meaning |
|---|---|
| **Green ring** | Tunnel is active — memory tools available to web chats |
| **Yellow pulsing ring** | Tunnel is starting (URL not yet received) |
| **No ring** | Tunnel is off |

### Popup controls

Click the extension icon to open the popup:

- **Toggle Global Capture** — enable/disable memory capture on all sites
- **Per-site toggle** — enable/disable capture on individual sites
- **Tunnel Status** — shows current tunnel state; click to start or stop
- **MCP Status** — shows whether the web chat is connected to MCP tools

---

## Quick reference

```bash
# Start everything
mnemostroma on              # start daemon
mnemostroma tray            # open system tray
mnemostroma tunnel start    # start tunnel (or use tray menu)

# Check status
mnemostroma status           # daemon + services
mnemostroma tunnel status    # tunnel URL + token

# Stop
mnemostroma tunnel stop      # from terminal
# Or use tray: Tunnel → Stop Tunnel
# Or use extension popup: click tunnel status
```
