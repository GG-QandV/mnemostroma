# Mnemostroma — Installation & Configuration

> RAM-first memory layer for AI agents. Connects to Claude Code, Cursor, Windsurf, Zed and other LLM clients via MCP (stdio) or SSE.

---

## Requirements

- Python 3.12+
- Linux / macOS (Windows: WSL2 recommended for full feature set)
- ~300 MB disk for ONNX models, ~630 MB RAM at runtime

---

## Installation

### Standard (pip)

```bash
# Core — daemon + MCP stdio adapter
pip install "git+https://github.com/GG-QandV/mnemostroma.git"

# With SSE adapter + passthrough proxy (captures Claude Code sessions)
pip install "git+https://github.com/GG-QandV/mnemostroma.git[sse]"
```

### First-time setup

```bash
mnemostroma setup
```

Downloads ONNX models (~300 MB), creates `~/.mnemostroma/`, generates TLS cert, writes `~/.local/bin/mnemo` launcher.

After setup:

```
~/.mnemostroma/
├── config.json            # tunable parameters (80+ options)
├── mnemostroma.db         # SQLite WAL — sessions, anchors, content
├── logs.db                # diagnostic logs (safe mode: no message content)
├── models/                # ONNX models
├── certs/                 # TLS cert for passthrough proxy (if [sse] installed)
│   ├── passthrough-ca.pem
│   ├── passthrough-cert.pem
│   └── passthrough-key.pem
├── daemon.sock            # IPC socket (present when daemon is running)
├── daemon.pid             # daemon PID
└── status.json            # health snapshot (updated every 30s)
```

---

## Starting the daemon

```bash
mnemostroma on       # start daemon in background
mnemostroma status   # check health, RAM, session count
mnemostroma off      # stop daemon
```

### Autostart (recommended)

```bash
mnemostroma service install   # installs systemd user units (Linux) or launchd (macOS)
```

Manual systemd management:

```bash
systemctl --user start   mnemostroma-daemon
systemctl --user stop    mnemostroma-daemon
systemctl --user status  mnemostroma-daemon
journalctl --user -u mnemostroma-daemon -f
```

---

## MCP Configuration (tools for agents)

The MCP stdio adapter connects agents to the daemon via IPC socket.
It does **not** call the Anthropic API directly.

### Claude Code (`~/.claude.json`)

```json
{
  "mcpServers": {
    "mnemostroma": {
      "command": "/home/yourname/.local/bin/mnemostroma",
      "args": ["mcp"]
    }
  }
}
```

> Find the correct path: `which mnemostroma`

### Claude Desktop (`claude_desktop_config.json`)

Same on all platforms — if `mnemostroma` is in PATH:

```json
{
  "mcpServers": {
    "mnemostroma": {
      "command": "mnemostroma",
      "args": ["mcp"]
    }
  }
}
```

Config locations: `~/.config/Claude/claude_desktop_config.json` (Linux/macOS) · `%APPDATA%\Claude\claude_desktop_config.json` (Windows)

### Cursor / Windsurf / Zed (IDE MCP config)

**Linux / macOS:**
```json
{
  "mcpServers": {
    "mnemostroma": {
      "command": "/path/to/venv/bin/python3",
      "args": ["-m", "mnemostroma.integration.mcp_stdio_adapter"]
    }
  }
}
```

**Windows:**
```json
{
  "mcpServers": {
    "mnemostroma": {
      "command": "C:\\path\\to\\venv\\Scripts\\python.exe",
      "args": ["-m", "mnemostroma.integration.mcp_stdio_adapter"]
    }
  }
}
```

> Find the path: `pip show mnemostroma` → look at `Location`, go one level up to `bin/` (Linux/macOS) or `Scripts/` (Windows).

---

## Passthrough Proxy (captures Claude Code sessions)

The proxy intercepts `/v1/messages` responses and sends extracted text to the Observer — without modifying requests or storing your API key.

**Requires:** `mnemostroma[sse]` + `mnemostroma setup` (generates TLS cert).

### Start

```bash
mnemostroma sse   # starts SSE adapter (port 8765) + passthrough proxy (port 8767)
```

### Launch Claude Code with memory capture

**Linux / macOS — use the `mnemo` wrapper (installed by setup):**

```bash
mnemo   # checks if proxy is running; if not, falls back to direct API silently
```

The wrapper does **not** set `ANTHROPIC_BASE_URL` if port 8767 is not listening — Claude Code works normally instead of crashing with connection refused.

**Windows (PowerShell) — set manually:**

```powershell
$env:ANTHROPIC_BASE_URL = "https://localhost:8767"
$env:NODE_EXTRA_CA_CERTS = "$env:USERPROFILE\.mnemostroma\certs\passthrough-ca.pem"
claude
```

### How the proxy works

```
mnemo → claude
           │
           └─ POST /v1/messages → https://localhost:8767 (proxy)
                                        │
                                        ├─ forward → https://api.anthropic.com
                                        ├─ stream response back to claude
                                        └─ extract text → IPC "observe" → daemon Observer
                                           (fire-and-forget, never blocks the stream)
```

Proxy is **fail-open**: if the daemon is down, requests pass through unmodified.

### Verify proxy is running

```bash
curl -sk https://localhost:8767/health
# {"status":"ok","metrics":{"requests":12,"observed":8,"skipped":4,"errors":0}}
```

---

## Available MCP Tools (11)

| Tool | Description |
|---|---|
| `ctx_semantic(query)` | Semantic search by meaning (~20ms, MatrixSearch ANN) |
| `ctx_get(id)` | Get session by ID |
| `ctx_search(tags)` | Filter by tags / importance / age |
| `ctx_anchors(type)` | Decisions, constraints, facts, deadlines (`type="deadline"`) |
| `ctx_precision(type)` | Verbatim facts: links, formulas, quotes |
| `ctx_full(id)` | Full session text from SQLite (for exact quoting) |
| `ctx_bridge()` | Handoff packet: intent + decisions + deadlines for next agent |
| `ctx_recent(days)` | Last N sessions by created / accessed date |
| `content_search(query)` | Semantic search over saved artifacts (code, docs) |
| `content_get(id)` | Artifact metadata by ID + version |
| `content_raw(id)` | Full raw text of artifact version |
| `content_history(id)` | Version lineage and change log |

> `ctx_active` → removed, context is injected automatically via `<memorycontext>` in system prompt.  
> `ctx_urgent` → merged into `ctx_anchors(type="deadline")`.  
> `ctx_load` → daemon-internal only (agents don't change RAM state).

---

## Troubleshooting

### MCP tools not visible

Check JSON validity — one syntax error disables all MCP servers:

```bash
python3 -m json.tool ~/.claude.json
```

### Daemon not starting

```bash
mnemostroma status
cat ~/.mnemostroma/daemon.log | tail -30
ls -la ~/.mnemostroma/daemon.sock
```

### `mnemo` falls back to direct API every time

Proxy not running — start it:

```bash
mnemostroma sse
```

Then in another terminal: `mnemo`

### `Tools return error: Mnemostroma not initialized`

Daemon not running:

```bash
mnemostroma on
```

### Proxy returns 502

Upstream connection failed — check network / API key:

```bash
curl -sk https://localhost:8767/health
```
