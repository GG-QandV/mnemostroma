# Mnemostroma: Storage Layer

Persistence management for memory, content branches, and telemetry. Formal PersistenceLayer boundary — memory logic never touches SQLite directly.

## Components
- `sqlite.py`: DatabaseManager — SQLite WAL orchestration, async queue, PersistenceLayer API.
- `persistence.py`: PersistenceLayer — isolation boundary between WorkingMemory and storage.
- `schemas.py`: SQLite schema definitions and migrations.
- `content_manager.py`: Versioned storage for code snippets and artifacts (Content Branch).
- `content.py`: Content data structures and diff logic.
- `lazy_loader.py`: Lazy session loader — loads archived sessions from SQLite to RAM on demand.
- `log_writer.py`: Diagnostic telemetry logger (writes to `logs.db` — Repo A only).
