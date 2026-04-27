# Mnemostroma Context Transfer — v5.0 (Release Sync)
> Created: 2026-04-04 | Logic Version: 1.7.x | Status: Ready for Public Release

## 1. Executive Summary
Mnemostroma has successfully transitioned to version **1.7.0**. This update marks the completion of the core Subconscious layers and the stabilization of the model stack. The project has moved from `hnswlib` to a custom `numpy`-based **MatrixSearch** for better stability and lower operational overhead in multi-task environments.

## 2. Technical State (v1.7.0)
| Component | Implementation | Notes |
|-----------|----------------|-------|
| **Semantic Search** | MatrixSearch (Numpy) | Replaced HNSWlib (ADR-002) |
| **Embedder** | Multilingual-E5-Small | 384d, ONNX INT8 |
| **Reranker** | TinyBERT-L2-v2 | ONNX INT8, 384d optimized |
| **NER Observer** | DistilBERT-NER + Regex | Hybrid approach |
| **Subconscious** | Dissolver + Tuner | Decay/Dreamer engine active |
| **Persistence** | SQLite WAL + LZ4 | Schema updated for `t_rel` |

## 3. Major Architectural Decisions
- **ADR-002: MatrixSearch**: We no longer use `hnswlib`. All semantic operations are performed via pure numpy cosine similarity on the memory Matrix. This ensures persistence consistency and simplifies the dependency tree.
- **Unified Dimension (384d)**: All embedding operations are now standardized at 384 dimensions to support the E5-small optimized stack.
- **Marker-based Memory**: The `marker()` pattern detection is now the primary driver for Anchor Layer creation.

## 4. Operational Updates
- **Safe Logging**: The system supports a `logging.enabled: false` mode in `config.json` to prevent sensitive context leakage in production.
- **CLI Automation**: `mnemostroma install-models` handles all ONNX weight downloads and verification.
- **Test Coverage**: Successfully passed **295/295 tests** on the v1.7 branch.

## 5. Transition for Developers
When interacting with the v1.7 codebase:
- Use `ctx.semantic(query)` for RAG.
- Use `ctx.active()` for current working memory.
- Consult `logging_specification.md` for the new `matrix.search` event keys.
- Never modify `src/` without an approved ADR.

---
*Mnemostroma Protocol | V5.0-TRANSFER | 2026-04-04*
