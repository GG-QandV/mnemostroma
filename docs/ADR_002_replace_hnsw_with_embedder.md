# ADR-002: Replace HNSW with Multilingual Embedder for Semantic Search

> Status: **ACCEPTED**
> Date: 2026-04-02
> Deciders: GG-QandV

---

## Context

Mnemostroma is a multilingual product. Users interact in RU, EN, UA and any other
language the embedding model supports. Sessions, entities, and memory objects contain
text in any of these languages.

**The architectural hole:**
HNSWlib operates on integer labels (`sid_to_id` / `id_to_sid` mapping).
The index has no concept of language — it stores float32 vectors and returns label IDs.
The hole is not in HNSWlib itself, but in the full stack around it:

1. The `filter.py` keyword lists (CRITICAL, IMPORTANT, CONFLICT) were RU/EN only
2. The `sid_to_id` / `id_to_sid` integer mapping is stateful and must be rebuilt
   from SQLite on every restart — fragile, order-dependent
3. HNSWlib requires the index to be warm (in RAM) to be useful — cold start problem
4. ANN approximation adds complexity (M, ef, ef_construction tuning) with no benefit
   at single-agent scale (< 50 000 sessions across a lifetime)

The decision to replace HNSW was made when designing the new `marker()` architecture
(see `instructions/MEMORY_SPEC_v2.md`) which requires clean multilingual semantics
from the ground up.

---

## Options Considered

**Option 1: Keep HNSW, add multilingual keyword lists to filter**
- Patch filter.py to support RU + EN + UA keywords
- Keep hnswlib for ANN
- ❌ Treats symptom, not cause. Still language-specific keyword matching.
  Still requires index rebuild on restart. Still has label mapping fragility.

**Option 2: Replace HNSW with SQLite FTS5 (full-text search)**
- Use SQLite's built-in full-text search index
- ❌ FTS5 is lexical (BM25), not semantic. Cannot find "решение" and "decision"
  as equivalent. Cross-language retrieval impossible.

**Option 3: Replace HNSW with a dedicated vector DB (Chroma, Qdrant, etc.)**
- External vector database with multilingual support
- ❌ Violates the core constraint: no external services, offline, single binary.
  Contradicts the product promise.

**Option 4 (CHOSEN): Use the embedding model directly as the search index**
- Store embeddings as float16 blobs in SQLite (already done)
- At search time: load all embeddings into a numpy matrix, compute cosine similarity
  in one vectorized operation, take top-K by argsort
- The model (multilingual-e5-small) produces embeddings in a shared semantic space
  regardless of input language — RU, EN, UA, ZH all map to the same 384-dim space
- ✅ Model doesn't care about language — semantic equivalence across languages
- ✅ No label mapping, no index rebuild, no warm-up required
- ✅ Removes hnswlib dependency entirely
- ✅ Simpler code, fewer failure modes
- ✅ At single-agent scale (< 50k sessions), brute-force numpy cosine is ~1-3ms
  — faster than HNSW with hydration overhead

---

## Decision

**Replace hnswlib with direct numpy cosine similarity over SQLite-stored embeddings.**

```python
# New search (conceptual):
async def semantic_search(query: str, ctx: SystemContext, top_k: int = 5):
    query_vec = await ctx.models.embedder.aencode(f"query: {query}")
    # All session embeddings loaded in RAM as (N, 384) float32 matrix
    scores = cosine_similarity_matrix(query_vec, ctx.session_matrix)
    top_indices = np.argsort(scores)[::-1][:top_k * 4]  # candidates for reranker
    candidates = [ctx.ram_index[ctx.idx_to_sid[i]] for i in top_indices]
    # Reranker (TinyBERT) still applies on top
    ...
```

The embedding model (multilingual-e5-small int8) handles language-agnostic semantics.
The system gains: "решил использовать PostgreSQL" ≡ "decided to use PostgreSQL" ≡
"вирішили використовувати PostgreSQL" — all map to similar vectors.

---

## Consequences

### Files to remove
- `src/mnemostroma/memory/hnsw.py` — delete entirely
- `hnswlib` from `pyproject.toml` dependencies

### Files to change (major)
- `src/mnemostroma/core.py` — remove `hnsw_session`, `hnsw_content`, `hnsw_lock`,
  `sid_to_id`, `id_to_sid`, `_next_hnsw_label`; add `session_matrix: np.ndarray`,
  `idx_to_sid: Dict[int, str]`
- `src/mnemostroma/memory/search.py` — replace KNN block with matrix cosine search
- `src/mnemostroma/conductor.py` — remove HNSW hydration (steps 3-5 bootstrap);
  build `session_matrix` from SQLite embeddings instead
- `src/mnemostroma/observer/pipeline.py` — remove `add_items` / label mapping
- `src/mnemostroma/observer/continuation_detector.py` — replace `knn_query` with
  matrix search or pre-computed similarity
- `src/mnemostroma/observer/calibration.py` — replace `knn_query`
- `src/mnemostroma/tuner/conflict.py` — replace `knn_query`
- `src/mnemostroma/storage/content_manager.py` — remove `hnsw_content.add_items`
- `src/mnemostroma/tools/bridge.py`, `tools/read.py` — remove label management
- `src/mnemostroma/tools/admin.py`, `tools/watch.py`, `tools/logs.py` — update stats
- `src/mnemostroma/__main__.py` — remove 10 HNSW config params
- `src/mnemostroma/config.py` — remove `HNSWConfig` section

### Tests to update
- `tests/test_continuation_detector.py` — replace `_mock_hnsw` with matrix mock
- `tests/test_bridge.py` — replace `hnsw_session` mock
- `tests/test_tuner/test_conflict.py` — replace `MockHNSW`
- `tests/test_behavioral.py` — remove `HNSWIndex` import

### Agent rules to update
- `.agents/rules/project-mnemostroma.md` — remove `hnswlib` from allowed deps

### Performance at scale
| Sessions | numpy cosine (384d) | hnswlib knn |
|----------|-------------------|-------------|
| 1 000 | ~0.3ms | ~0.5ms + hydration |
| 10 000 | ~2ms | ~1ms + hydration |
| 50 000 | ~8ms | ~1.5ms + hydration |

At 10k+ sessions numpy starts to lose vs HNSW on raw speed, but:
- No hydration cost (HNSW rebuilds on restart: ~500ms at 10k)
- No label mapping fragility
- Multilingual semantic correctness outweighs 6ms latency at this scale

If the corpus exceeds 50k sessions: re-evaluate. For v2 target this is not a concern.

---

## Pipeline Parallelism: 2×2 default, 4×4 optional

HNSW was called at four independent points in the pipeline:
1. Continuation detection (`pipeline.py` — inside `hnsw_lock`)
2. Conflict detection (`conflict.py` — inside `hnsw_lock`)
3. Calibration (`calibration.py` — inside `hnsw_lock`)
4. Semantic search (`search.py` — inside `hnsw_lock`)

Because all four shared one `hnsw_lock`, they were effectively **serial**.

With numpy matrix search, the lock is gone. Parallelism is now controlled by
`resources.onnx_inter_threads` × `resources.onnx_intra_threads` in `config.json`.

**Current default — 2×2** (e5-small int8, 631MB RAM budget):
```json
"onnx_inter_threads": 2,
"onnx_intra_threads": 2
```
- 2 inter-op: up to 2 embedding calls can overlap (e.g., NER + embed in parallel)
- 2 intra-op: each ONNX op uses 2 CPU threads internally
- Total: ~4 CPU threads, fits within the 631MB RAM envelope

**Power user mode — 4×4** (larger model, more RAM available):
```json
"onnx_inter_threads": 4,
"onnx_intra_threads": 4
```
- 4 inter-op: continuation + conflict + calibration + search can all run in parallel
- 4 intra-op: each ONNX op uses 4 CPU threads
- Enables full 4-way parallelism of the four search points listed above
- Appropriate when user upgrades to a larger embedding model and has > 1.5GB RAM budget

**Config section replacing `hnsw`** (to add to `config.json`):
```json
"search": {
    "top_k_candidates": 20,
    "top_n_results": 5,
    "embedding_dim": 384,
    "matrix_dtype": "float32",
    "pipeline_width": 2
}
```
`pipeline_width` = how many of the 4 search points run concurrently.
- `2` = NER‖Embed already parallel (current); continuation+conflict sequential
- `4` = all four points parallel; requires `onnx_inter_threads >= 4`

The config validator enforces: `pipeline_width <= onnx_inter_threads`.

---

## Related
- `instructions/MEMORY_SPEC_v2.md` — anchor vectors for entity classification (same model)
- `instructions/MEMORY_MODEL_v2.md` — multilingual design principle
- ADR-001: Script vs Model decisions
- `CONTRIBUTING_INTERNAL.md` — language policy

---

---

## Implementation Notes (2026-04-03)

Status: **IMPLEMENTED** (diverges from plan in 3 points — all intentional)

| Plan | Actual | Reason |
|------|--------|--------|
| Delete `memory/hnsw.py` | Rewritten as `MatrixSearch` class, kept | Drop-in API compatibility; callers unchanged |
| `session_matrix: np.ndarray` in SystemContext | `session_index: MatrixSearch` | Encapsulates add/query; same numpy internals |
| `idx_to_sid: Dict[int, str]` naming | `id_to_sid` kept | No semantic change; renaming renamed `hnsw_session→session_index` etc. |

All HNSW field names removed from codebase (commit 9bd6e52):
`hnsw_session→session_index`, `hnsw_content→content_index`, `hnsw_lock→index_lock`,
`get_hnsw_label→get_session_label`, `_next_hnsw_label→_next_session_label`.

Embed+NER parallelised at pipeline step 1 (commit b8751a5):
`gather(aencode, ner.extract)` before `marker()` — latency reduced from
`embed+NER sequential (30-80ms)` to `max(embed, NER) (20-50ms)` on 6+ cores.

---

*ADR-002 | 2026-04-02 | Status: IMPLEMENTED | Replaces: hnswlib ANN*
