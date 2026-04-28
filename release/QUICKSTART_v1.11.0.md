# Quick Start — Mnemostroma v1.11.0

## 🧠 Autonomous Memory & Temporal Precision

Mnemostroma v1.11.0 is the most advanced version of the memory layer yet, featuring autonomous content capture and high-precision temporal search.

### Key Features

- **Autonomous Content Branch**: No more manual `save_content`. The system automatically detects code and research and persists it to the content branch.
- **Temporal Search**: Surgical precision when looking for memory in specific time windows.
- **Minimized API**: A cleaner, more robust MCP interface focused on retrieval and action.

---

### Installation

**Option A: Automatic (Linux/macOS)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/windows/install-daemon.ps1 -OutFile install-daemon.ps1; .\install-daemon.ps1"
```

---

### Technical State (v1.11.0)

<details>
<summary><b>Benchmarks & Stability</b></summary>

- **Tests**: 501/501 passed (100% Green).
- **RAM Footprint**: ~340MB (Baseline) / ~650MB (Peak).
- **Search Latency**: ~20ms (Semantic) / ~5ms (Exact Time SQL).

</details>

<details>
<summary><b>Autonomous Mechanics (v1.11.0)</b></summary>

- **Mechanism #12**: `PersistStep` now includes a `classify_session_type` call. Code/Research artifacts are automatically captured.
- **Exact Time**: `content_search` and `ctx_search` now support high-precision temporal windows.

</details>

---

### License

**FSL-1.1-MIT**
Commercially restricted for the first 2 years, then MIT. For personal use - **free forever**.

---
**Generated:** 2026-04-28
**v1.11.0** | 501 tests green | [Full Release Notes](./RELEASE_NOTES_v1.11.0.md)
