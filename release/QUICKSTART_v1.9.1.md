# Mnemostroma Quickstart — v1.9.1

Mnemostroma is a local memory layer for AI agents. It automatically captures decisions, constraints, and key facts, making them available across sessions through structured retrieval and automatic context injection.

## Requirements
- Python 3.12+
- Linux (Systemd), macOS (Launchd), or Windows 10/11 (Task Scheduler)

## Installation

**Option A: Automatic (Linux & macOS)**
One command. Creates venv, installs everything, downloads models, and configures background services.
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Automatic (Windows)**
Run in an elevated (Administrator) PowerShell:
```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/windows/install-daemon.ps1 -OutFile install-daemon.ps1; .\install-daemon.ps1"
```

**Option C: Manual / pipx**
If your system blocks `pip install` (PEP 668):
```bash
sudo apt install pipx && pipx ensurepath
pipx install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
mnemostroma setup
mnemostroma download-models
mnemostroma service install
```

## Start
The background agents (Daemon, Proxy, Watchdog) will start automatically upon installation. To verify health:
```bash
mnemostroma status
```
*(On Linux/macOS, use the `mnemo-health` alias for a deep check).*

## Optional: Claude Code Integration
To capture Claude Code sessions automatically via our local HTTP Proxy:
```bash
mnemostroma sse
mnemo
```

## What it provides
- **Persistent Memory**: Cross-session history and facts.
- **Automatic Capture**: The Observer pipeline tracks your work without manual input.
- **AutoBridge**: Pre-computes context packages for seamless agent handoffs.
- **Decision Recovery**: High-precision extraction of previous decisions and prohibitions.
- **Local-first**: 100% offline; no data is sent to external servers.

## License
**FSL-1.1-MIT** — Commercially restricted for 2 years, then MIT. Free for personal use.
