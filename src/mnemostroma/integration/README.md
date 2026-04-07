# Mnemostroma: Integration Layer

Provides the bridge between Mnemostroma and external LLM agents.

## Components
- `ConductorProxy`: Middleware for prompt injection and XML memory context formatting.
- `MemoryBlock`: Standardized data structure for LLM-ready context.
- `mcp_server`: MCP stdio transport server exposing Mnemostroma tools to AI agents.

## Data Flow (MCP)
```
Agent (Antigravity) → stdio JSON-RPC → mcp_server.py → tools/*.py → SystemContext → RAM/SQLite
```

## Running
```bash
PYTHONPATH=src .venv/bin/python3 -m mnemostroma.integration.mcp_server
```
