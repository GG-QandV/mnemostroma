# Mnemostroma: Integration Layer

Adapters connecting Mnemostroma to external LLM agents and clients.

## Components
- `mcp_stdio_adapter.py`: MCP stdio transport — entry point for Claude Code and CLI agents.
- `mcp_sse_adapter.py`: MCP SSE transport — HTTP server for claude.ai and browser clients (port 8765). Auth via Bearer token.
- `mcp_server.py`: Legacy MCP server (kept for compatibility).
- `proxy.py`: API proxy middleware for transparent memory injection into LLM API calls.
- `sdk.py`: SDK helpers for agent integration.

## Architecture
All adapters connect to the daemon via IPC socket (`~/.mnemostroma/daemon.sock`).
The daemon (Conductor) is the single authority — adapters never import conductor directly.

## Data Flow
```
Agent      → mcp_stdio_adapter → IPC socket → Conductor → tools/*.py → RAM/SQLite
claude.ai  → mcp_sse_adapter   → IPC socket → Conductor → tools/*.py → RAM/SQLite
```

## Running
```bash
mnemostroma mcp   # stdio adapter (Claude Code)
mnemostroma sse   # SSE adapter (claude.ai)
```
