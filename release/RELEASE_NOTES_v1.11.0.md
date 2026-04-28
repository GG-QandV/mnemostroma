# Release Notes — Mnemostroma v1.11.0

## 🚀 Content Branch Automation & Temporal Precision

This release marks a major architectural milestone. Mnemostroma now moves from a "passive storage" model to an **autonomous cognitive substrate**. The system now automatically identifies and routes development artifacts without explicit agent commands, while adding surgical precision to temporal memory retrieval.

### Key Highlights

- **Content Branch Automation (Mechanism #12)**: 
  The Observer pipeline now autonomously classifies sessions. If a session contains significant code snippets, research findings, or documentation updates, it is automatically routed to the `ContentManager`. 
  - **Result**: Agents no longer need to call `save_content` manually. Memory is captured as it happens.

- **Exact Time Search**:
  Temporal memory retrieval has been upgraded to "surgical" precision. You can now query memory with high-precision temporal windows (SQL + Semantic hybrid).
  - **Benefit**: "What did we decide between 2:15 PM and 2:30 PM yesterday?" is now a native capability.

- **API Minimization (The Invariant Push)**:
  To enforce the architectural invariant **"Observer writes, Agent acts"**, we have muted redundant write tools in the MCP server:
  - `save_content` (now automated)
  - `content_get` (now integrated into `content_search` / `content_raw`)
  - `ctx_expire` & `ctx_urgent` (handled by internal decay/bridge logic)

- **Test Coverage**: 
  The test suite has expanded to **501 green tests**, covering 100% of the new classification and temporal search logic.

---

### Detailed Changelog

- `feat(observer)`: **Mechanism #12** — Automated content routing in `PersistStep`.
- `feat(observer)`: New **Session Classifier** (code, research, context) for autonomous routing.
- `feat(storage)`: **Exact Time Search** — Hybrid SQL/Semantic search with micro-window filtering.
- `refactor(mcp)`: Muted deprecated write tools to simplify the agent interface and reduce "hallucinated" memory writes.
- `fix(persistence)`: Improved `PersistenceLayer` batching for high-frequency content updates.
- `fix(tuner)`: Semantic drift detection now accounts for content-branch updates.

---

**Generated:** 2026-04-28
**Mnemostroma:** The memory layer for AI agents
**v1.11.0** | 501 tests passing | 0 regressions
