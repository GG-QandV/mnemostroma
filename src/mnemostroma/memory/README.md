# Mnemostroma: Memory Layer

Core vector indexing and semantic logic.

## Components
- `MatrixSearch` (`hnsw.py`): Numpy-based cosine ANN search. Replaced hnswlib (ADR-002). `HNSWIndex` is a compatibility alias.
- `Dissolver`: Logic for memory fading and conflict detection during consolidation.
- `ConsolidationWorker`: Background process for Hot→Warm→Cold migration.
- `ExperienceIndex`: Long-term experience clusters with decay support.
- `Reranker`: TinyBERT cross-encoder for result reranking (lazy-loaded).
