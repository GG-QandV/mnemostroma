# Release Notes — Mnemostroma v2.4.0

## Subconscious Core Gaps (GAP-1 & GAP-2)

Mnemostroma v2.4.0 introduces the core architectural foundations for the Subconscious Layer (Hypómnema Strōma v3.0). This release enables the system to track *how* tasks are solved (process patterns) and generate subconscious intuition signals (`confidence` / `caution`) based on past experiences.

---

### Key Changes

#### 1. Process Vector Generation (GAP-1)

- **`step_log` tracking**: The Observer now collects `step_log` entries per session (limited to 500 steps per session).
- **`process_vec` builder**: Added `build_process_vec()` that encodes the sequence of step importances and dominant tags into a single `384d f16` vector using `multilingual-e5-small`. This vector captures the *pattern* of the session, not just its content.
- **Background Flush**: The `Dreamer` idle worker now automatically flushes `step_logs` to SQLite (`session_steps` table) and builds process vectors in the background.

#### 2. Subconscious Evaluator v1.5 (GAP-2)

<img src="https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/src/extension/assets/head-circuit-256.png" width="96" align="right" />

- **Polarity Matrix**: `ExperienceCluster` now separates vectors into `positive_vecs` and `negative_vecs`.
- **Exponential Decay**: Negative experience vectors decay over time according to a strict mathematical formula: `np.maximum(floor, w0 * exp(-λ * age_days))`.
- **Cosine Evaluator**: The new `subconscious_evaluate()` function performs vectorised matmul across the cluster matrix to generate intuition signals (`confidence` or `caution`) in ≤0.5ms.
- **Memory Block Wiring (B5)**: Signals are drained and rendered into the `<subconscious>` XML block injected into the prompt. Priority: `TENSION > caution > REPEL > AMBIVALENT > ATTRACT > confidence > DO_THIS > AVOID_THIS`.

#### 3. New SQLite Tables

- `session_steps`: Stores individual steps (`session_id`, `msg_index`, `ts`, `importance`, `tags`, `outcome`).
- `experience_vectors`: Stores `f16` embeddings for experience clustering (`tag`, `charge`, `vec`, `dim`, `w0`, `ts`).

#### 4. Config Controls

New configurable thresholds in `config.json`:
- `evaluator_vecs_cap`: 50
- `closure_idle_sec`: 1800
- `step_log_sessions_cap`: 100
- Active configuration parameters: `process_vec_enabled`, `negative_exp_lambda`, `negative_exp_resolution_floor`, `cluster_min_samples`.

---

### Upgrade Instructions

See [UPGRADE.md](../UPGRADE.md) → *Upgrading to v2.4.0*

**TL;DR:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma off && mnemostroma on
```

---

### Technical State

- **Tests**: 1258 passing (+332 new tests for polarity and evaluator)
- **RAM Footprint**: ~711 MB baseline (daemon ~522 MB with 1936 active sessions)
- **Search Latency**: ~20ms semantic / ~5ms SQL / ≤0.5ms evaluator
- **Regressions**: 0

---

**Generated:** 2026-06-12  
**Mnemostroma:** The offline-first memory layer for AI agents  
**v2.4.0** | 1258 tests passing | 0 regressions | Subconscious Core Release
