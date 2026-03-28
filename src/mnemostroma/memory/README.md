# Mnemostroma: Memory Layer

Core vector indexing and semantic logic.

## Components
- `HNSWIndex`: Wrapper for `hnswlib` ANN search.
- `Dissolver`: Logic for memory fading and conflict detection during consolidation.
- `ConsolidationWorker`: Background process for Hot->Warm->Cold migration.
