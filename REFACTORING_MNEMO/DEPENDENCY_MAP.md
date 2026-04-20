# DEPENDENCY_MAP.md
# Version: v1.7.5-pre-refactor (Phase 0 snapshot)
# Updated: Automated + Review after each phase

## 1. Module Dependency Graph (Current State)

| From Module | To Module | Type | Allowed Post-Refactor |
|:---|:---|:---|:---|
| observer/pipeline.py | storage/sqlite.py | DIRECT WRITE | ❌ → via PersistencePort |
| tools/read.py | memory/search.py | CALL | ✅ keep |
| tools/read.py | storage/sqlite.py | DIRECT READ | ❌ → via SessionPort |
| main.py | tuner/conductor.py | INIT | ✅ → core/bootstrap.py |
| mcp_server.py | tools/read.py | DISPATCH | ✅ → via MCPToolPort |
| subconscious/dreamer.py | storage/sqlite.py | DIRECT | ❌ → via PersistencePort |

## 2. Forbidden Relationships Post-Refactor

- `domain/*` → `adapters/*` (FORBIDDEN)
- `domain/*` → `ports/*` (FORBIDDEN: domain is port-agnostic)
- `observer/steps/*` → `adapters/sqlite/*` (FORBIDDEN: use Port DI)
- `tools/*` → `storage/sqlite.py` (FORBIDDEN: use Repos)

## 3. Mandatory New Connections (Contracts)

| From | To (Port) | Implementation | Phase |
|:---|:---|:---|:---|
| observer/steps/persist.py | ports/output/session_port.py | adapters/sqlite/session_repo.py | Phase 2 |
| tools/memory/semantic.py | ports/output/session_port.py | adapters/sqlite/session_repo.py | Phase 3 |
| core/monitoring.py | — (TaskGroup) | — | Phase 1 |
