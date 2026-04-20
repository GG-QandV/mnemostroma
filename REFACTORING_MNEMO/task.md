# [COMPLETED] Task: Mnemostroma Modularization (v5.0) — 2026-04-14

## Phase 0: Baseline & Integrity Setup
- [x] **0.1** MCP Contract Export (`scripts/gen_mcp_schemas.py`)
- [x] **0.2** Performance Baseline & Benchmarks
- [x] **0.3** **Create Core Integrity Docs**:
    - [x] `DEPENDENCY_MAP.md` (Architectural layers)
    - [x] `CONTRACT_REGISTRY.md` (Go-blueprint)
    - [x] `LATENCY_INVARIANTS.md` (Performance budgets)
- [x] **0.4** **Integrity CI Scripts**:
    - [x] `scripts/check_dependencies.py`
    - [x] `scripts/gen_contracts.py`
    - [x] `scripts/check_latency_structure.py`
- [x] **0.5** Tooling Bootstrap (`uv`, `ruff`, `mypy`)
- [x] **0.6** Git Tag `v1.7.5-pre-refactor`

## Phase 1: main.py & core/ Decomposition
- [x] **1.1** Skeleton: Create `cli/` and `core/` packages
- [x] **1.2** Domain Types: `domain/types.py` (Result aliases)
- [x] **1.3** `core/lifecycle.py` (Signal handlers)
- [x] **1.4** `core/bootstrap.py` (Init sequence)
- [x] **1.5** `core/monitoring.py` (TaskGroup)
- [x] **1.6** Extract `cli/` commands (Moved up in logic)
- [x] **1.7** Cleanup `main.py` (< 30 lines)
- [x] [CI] Run Integrity Check (Baseline 424/11 -> **435/0 Passed**)

## Phase 2: Ports & Adapters (Hexagon)
- [x] **2.1** ports/output/session_port.py      ← Protocol + сигнатуры  [Pro]
- [x] **2.2** ports/output/anchor_port.py       ← Protocol               [Pro]
- [x] **2.3** ports/output/embedder_port.py     ← Protocol               [Pro]
- [x] **2.4** adapters/sqlite/session_repo.py   ← реализация SessionPort [Pro]
- [x] **2.5** ShadowSessionRepo                 ← параллельный запуск    [Pro]
- [x] **2.6** config flip: shadow mode on       ← 24h мониторинг         [Flash: тест]
- [x] **2.7** adapters/sqlite/anchor_repo.py    ← реализация AnchorPort  [Flash]
- [x] **2.8** adapters/onnx/embedder.py         ← реализация EmbedderPort[Flash]
- [x] **2.9** удалить legacy после 24h stable   ← legacy-removal коммит  [Flash]
- [x] [CI] Run Integrity Check (435/0 Passed)

## Phase 2.5: Observer StepChain
- [x] **2.5.1** `PipelineContext` (Domain pure)
- [x] **2.5.2** `steps/` extraction (NER, Embed, Rerank)
- [x] **2.5.3** DI for `PersistStep` (Repo-based)
- [x] [CI] Run Latency Invariant Tests (passed)

## Phase 3: Tools & Go-Blueprint
- [x] **3.1** Subpackages: `read`, `write`, `content`, `admin`
- [x] **3.2** Final Interface Audit (12 active tools)
- [x] **3.3** MCP Contract Verification vs Phase 0 (100% test pass)
- [x] [CI] Final Integrity Report
- [x] **3.4** Git Tag `v1.8.0-modular-complete` (Pushed to core)

# [mnemostroma-protocol]
## Memory Protocol (Mnemostroma)

You have persistent memory tools. This is not optional guidance —
this is how you operate.

REQUIRED at session start (before your first response):
  → call ctx_active()

REQUIRED when user references past work, decisions, or prior context:
  → call ctx_semantic(query) or ctx_search(tags)

REQUIRED before session ends (if any decisions made or work continues):
  → call ctx_bridge()

Rules:
- Never say "I don't have context from previous sessions"
  without first calling ctx_active()
- Not using memory tools when they are available is an error
- The user expects continuity across sessions
# [mnemostroma-protocol]-end
