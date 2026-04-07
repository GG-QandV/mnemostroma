# SPDX-License-Identifier: FSL-1.1-MIT
"""§6.2 Reranker E2E integration test.

Tests real ONNX models from models/ directory.
Auto-skipped when model files are absent (CI without models).

Models used:
  - multilingual-e5-small/onnx/model_int8.onnx  → embedder (dim=384)
  - tinybert-l2-v2/onnx/model_quint8_avx2.onnx  → cross-encoder reranker
"""
import numpy as np
import pytest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RERANKER_MODEL     = PROJECT_ROOT / "models/tinybert-l2-v2/onnx/model_quint8_avx2.onnx"
RERANKER_TOKENIZER = PROJECT_ROOT / "models/tinybert-l2-v2/tokenizer.json"
EMBEDDER_MODEL     = PROJECT_ROOT / "models/multilingual-e5-small/onnx/model_int8.onnx"
EMBEDDER_TOKENIZER = PROJECT_ROOT / "models/multilingual-e5-small/tokenizer.json"

needs_models = pytest.mark.skipif(
    not RERANKER_MODEL.exists() or not EMBEDDER_MODEL.exists(),
    reason="Model files not present — run: mnemostroma install-models",
)


# ── Embedder ──────────────────────────────────────────────────────────────────

@needs_models
def test_embedder_output_shape():
    from mnemostroma.models.onnx_engine import ONNXEmbeddingEngine
    engine = ONNXEmbeddingEngine(EMBEDDER_MODEL, EMBEDDER_TOKENIZER, dim=384)
    vec = engine.encode("semantic memory architecture")
    assert vec.shape == (384,), f"Expected (384,), got {vec.shape}"
    engine.close()


@needs_models
def test_embedder_dtype_float16():
    from mnemostroma.models.onnx_engine import ONNXEmbeddingEngine
    engine = ONNXEmbeddingEngine(EMBEDDER_MODEL, EMBEDDER_TOKENIZER, dim=384)
    vec = engine.encode("test output dtype")
    assert vec.dtype == np.float16
    engine.close()


@needs_models
def test_embedder_l2_normalized():
    from mnemostroma.models.onnx_engine import ONNXEmbeddingEngine
    engine = ONNXEmbeddingEngine(EMBEDDER_MODEL, EMBEDDER_TOKENIZER, dim=384)
    vec = engine.encode("L2 normalization check").astype(np.float32)
    norm = float(np.linalg.norm(vec))
    assert abs(norm - 1.0) < 0.02, f"Expected L2 norm ≈ 1.0, got {norm:.4f}"
    engine.close()


@needs_models
def test_embedder_cosine_similar_texts_closer():
    """Semantically similar texts must be closer than dissimilar ones."""
    from mnemostroma.models.onnx_engine import ONNXEmbeddingEngine
    engine = ONNXEmbeddingEngine(EMBEDDER_MODEL, EMBEDDER_TOKENIZER, dim=384)
    va = engine.encode("machine learning neural networks").astype(np.float32)
    vb = engine.encode("deep learning AI models training").astype(np.float32)
    vc = engine.encode("italian pasta cooking recipe tomato").astype(np.float32)
    sim_ab = float(np.dot(va, vb))
    sim_ac = float(np.dot(va, vc))
    assert sim_ab > sim_ac, (
        f"Expected sim(ML, DL)={sim_ab:.3f} > sim(ML, pasta)={sim_ac:.3f}"
    )
    engine.close()


@needs_models
@pytest.mark.asyncio
async def test_embedder_aencode_matches_encode():
    """aencode must return same shape as encode."""
    from mnemostroma.models.onnx_engine import ONNXEmbeddingEngine
    engine = ONNXEmbeddingEngine(EMBEDDER_MODEL, EMBEDDER_TOKENIZER, dim=384)
    sync_vec = engine.encode("async encode parity check")
    async_vec = await engine.aencode("async encode parity check")
    assert sync_vec.shape == async_vec.shape
    engine.close()


# ── Reranker (memory/reranker.py — correct pair tokenization) ─────────────────

@needs_models
def test_reranker_rank_output_length():
    from mnemostroma.memory.reranker import Reranker
    r = Reranker(RERANKER_MODEL, RERANKER_TOKENIZER)
    docs = ["Python garbage collection", "SQL query optimizer", "pasta recipe"]
    scores = r.rank("Python memory management", docs)
    assert len(scores) == 3


@needs_models
def test_reranker_scores_in_unit_interval():
    from mnemostroma.memory.reranker import Reranker
    r = Reranker(RERANKER_MODEL, RERANKER_TOKENIZER)
    scores = r.rank("database indexing", ["B-tree index structure", "chocolate cake"])
    for s in scores:
        assert 0.0 <= s <= 1.0, f"Score out of [0,1]: {s}"


@needs_models
def test_reranker_relevant_beats_irrelevant():
    """Relevant document must score higher than irrelevant."""
    from mnemostroma.memory.reranker import Reranker
    r = Reranker(RERANKER_MODEL, RERANKER_TOKENIZER)
    query = "Python asyncio event loop coroutine"
    relevant   = "asyncio provides infrastructure for writing single-threaded concurrent code using coroutines"
    irrelevant = "the best way to bake sourdough bread is with a cast iron dutch oven"
    scores = r.rank(query, [relevant, irrelevant])
    assert scores[0] > scores[1], (
        f"relevant={scores[0]:.3f} should be > irrelevant={scores[1]:.3f}"
    )


@needs_models
def test_reranker_empty_returns_empty():
    from mnemostroma.memory.reranker import Reranker
    r = Reranker(RERANKER_MODEL, RERANKER_TOKENIZER)
    assert r.rank("query", []) == []


# ── TinyBERTReranker (models/reranker.py — agent-facing wrapper) ──────────────

@needs_models
def test_tinybert_reranker_output_format():
    """`rerank()` must return List[Tuple[str, float]] sorted desc by score."""
    from mnemostroma.models.reranker import TinyBERTReranker
    r = TinyBERTReranker(str(RERANKER_MODEL), str(RERANKER_TOKENIZER))
    candidates = ["neural network training", "cake recipe", "gradient descent"]
    results = r.rerank("machine learning optimization", candidates)

    assert len(results) == len(candidates)
    for doc, score in results:
        assert isinstance(doc, str)
        assert isinstance(score, float)
    scores = [s for _, s in results]
    assert scores == sorted(scores, reverse=True), "Must be sorted descending"


@needs_models
def test_tinybert_reranker_empty():
    from mnemostroma.models.reranker import TinyBERTReranker
    r = TinyBERTReranker(str(RERANKER_MODEL), str(RERANKER_TOKENIZER))
    assert r.rerank("query", []) == []


@needs_models
def test_tinybert_reranker_lazy_load():
    """Model must not be loaded until first rerank() call."""
    from mnemostroma.models.reranker import TinyBERTReranker
    r = TinyBERTReranker(str(RERANKER_MODEL), str(RERANKER_TOKENIZER))
    assert not r._loaded
    r.rerank("test", ["doc"])
    assert r._loaded
