# Mnemostroma: Models (ONNX)

Lazy-loading wrappers for ONNX INT8 models. No torch, no transformers.

## Models
- **SessionEmbedder / ContentEmbedder**: Multilingual-E5-Small INT8 (384d) — shared embedder for sessions and content.
- **HybridNER**: DistilBERT INT8 + multilingual regex patterns (DECISION, PROHIBITION, TECH).
- **Reranker**: TinyBERT-L2-v2 INT8 — cross-encoder reranking, lazy-loaded on first use.

## Components
- `onnx_engine.py`: Core ONNX Runtime inference wrapper.
- `engine_pool.py`: Shared model pool (singleton per process).
- `hybrid_ner.py`: HybridNER — ONNX NER + rule-based fallback.
- `ner_observer.py`: NER adapter for the observer pipeline.
- `bert_ner.py`: Low-level DistilBERT NER wrapper.
- `content_embedder.py`: Content branch embedder.
- `reranker.py`: TinyBERT cross-encoder reranker.
- `embedding_utils.py`: Pooling and normalization utilities.
- `protocol.py`: Model interface protocol / typing.
- `mock_engine.py`: Mock engine for testing without ONNX models.
