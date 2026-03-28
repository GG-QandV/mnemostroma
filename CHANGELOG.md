# Changelog

All notable changes to the **Mnemostroma** project will be documented in this file.

## [1.5.1] - 2026-03-26

### Added

- **Configuration Centralization**: All implicit feedback weights, EMA alpha, and SQLite resource Pragmas moved to `config.json`.
- **Modular Pipeline**: Extracted `compress_text` and scoring helpers to `observer/utils.py` and `memory/scoring.py`.

### Fixed

- **EMA Calculation**: Corrected formula in `implicit.py` to ensure baseline scaling (neutral signals no longer drift to 0.9).
- **Shutdown Reliability**: Fixed race condition in `DatabaseManager.stop()` ensuring full queue flush before worker exit.
- **Index Consistency**: Unified HNSW labeling logic in `SystemContext.get_hnsw_label()` to resolve `sid_to_id` mapping errors.
- **SQLite Performance**: Pragmas (cache/mmap) are now dynamically loaded from config.

## [1.5.0] - 2026-03-26

### Added

- **Phase 7 Implementation**: 
  - `ModelRegistry` ONNX lazy-loading wrappers (`session_embedder`, `content_embedder`, `ner_observer`, `reranker`).
  - `ConductorProxy` integration layer for XML-based context injection into LLM prompts.
  - `tools/admin.py` with `ctx.status()`, `ctx.sync()`, and `ctx.dump()`.
- **Conflict Detector (Phase 3)**: Semantic dissonance detection using HNSW cosine similarity and Levenshtein distance.
- **Feedback Loop (v1.5)**: `ImplicitFeedbackTracker` for automated USE/IGNORE signal processing.
- **Persistence Layer**: Log instrumentation (18 points) and `logs.db` storage.

### Fixed

- **Architectural Compliance**: 
  - Added missing `deep_use_count` and `last_use_ts` to `sessions` table.
  - Enabled feedback field persistence in `DatabaseManager` flush logic.
  - Refactored `ContentManager` to use unified async queue for non-blocking writes.
  - Resolved `Dissolver` operational gap by enabling background RAM eviction loop.
  - Normalized Content branch embeddings to `float16` for system-wide consistency.
- **EMA Scoring**: Corrected formula in `ImplicitFeedbackTracker` for neutral/negative signals.
- **HNSW Content Index**: Corrected initialization with high-precision parameters (M=32, ef=400).
- **SystemContext (T04)**: Migrated from `Optional[Any]` to strict typing and unified infrastructure access.
- **HNSW Safety**: Added checks for empty indices in `knn_query` to prevent runtime crashes.
- **NER Mock**: Fixed TypeError in `observer_pipeline` regarding empty metadata.

### Security

- **Fail-fast Core**: Added `__post_init__` to `ModelRegistry` to ensure local model storage directory existence.

## [1.0.0] - 2026-03-24

- Initial project bootstrap: Conductor, Observer, RAM Index.
