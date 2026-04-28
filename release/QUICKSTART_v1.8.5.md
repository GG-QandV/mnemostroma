# Mnemostroma Quickstart — v1.8.5

Mnemostroma is a local memory layer for AI agents. It automatically captures decisions, constraints, and key facts, making them available across sessions through structured retrieval and automatic context injection.

## Requirements
- Python 3.12+
- Linux (Systemd recommended), macOS, or Windows

## Installation

**Option A: Automatic (Recommended)**
One command. Creates venv, installs everything, configures systemd.
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Manual / pipx**
If your system blocks `pip install` (PEP 668):
```bash
sudo apt install pipx && pipx ensurepath
pipx install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
mnemostroma setup
mnemostroma service install
```

## Start
```bash
mnemostroma on
mnemostroma status
```

## Optional: Claude Code Integration
To capture Claude Code sessions automatically:
```bash
mnemostroma sse
mnemo
```

## What it provides
- **Persistent Memory**: Cross-session history and facts.
- **Automatic Capture**: The Observer pipeline tracks your work without manual input.
- **Semantic Retrieval**: Relevant past context is injected automatically via `<memorycontext>`.
- **Decision Recovery**: High-precision extraction of previous decisions and prohibitions.
- **Local-first**: 100% offline; no data is sent to external servers.

## License
**FSL-1.1-MIT** — Commercially restricted for 2 years, then MIT. Free for personal use.
