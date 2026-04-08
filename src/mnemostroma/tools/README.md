# Mnemostroma: Tools Layer

MCP tool implementations exposed to agents. All tools are read-only from the agent's perspective — Observer handles all writes.

## Components
- `read.py`: Semantic search, anchor retrieval, precision data, urgent tasks (`ctx_active`, `ctx_semantic`, `ctx_search`, `ctx_anchors`, `ctx_precision`, `ctx_urgent`, `ctx_expire`).
- `bridge.py`: Session handoff packet generation (`ctx_bridge`, `ctx_full`, `ctx_get`, `ctx_load`).
- `content.py`: Content branch tools — versioned artifact storage and search (`save_content`, `content_search`, `content_get`, `content_raw`, `content_history`).
- `admin.py`: Admin tools — session eviction, metrics (`ctx_evict`).
- `write.py`: Internal write helpers (not exposed to agents directly).
- `logs.py`: Log analysis CLI tool (`mnemostroma logs`).
- `watch.py`: Live terminal dashboard (`mnemostroma watch`).
- `tray.py`: System tray status indicator (`mnemostroma tray`, requires `mnemostroma[tray]`).
