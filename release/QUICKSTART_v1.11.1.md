# Quick Start — Mnemostroma v1.11.1

## 🧠 Autonomous Memory & Temporal Precision — Installer Stability Patch

Mnemostroma v1.11.1 is a stability patch for the installer pipeline. All v1.11.0 features are intact.

### Key Features (inherited from v1.11.0)

- **Autonomous Content Branch**: No more manual `save_content`. The system automatically detects code and research and persists it to the content branch.
- **Temporal Search**: Surgical precision when looking for memory in specific time windows.
- **Minimized API**: A cleaner, more robust MCP interface focused on retrieval and action.

### What's new in v1.11.1

- Installer no longer crashes with `FileNotFoundError: models_manifest.json` on fresh installs.
- `bash <(curl ...)` mode no longer fails with `/dev/fd/linux/install.sh: No such file or directory`.
- Editable dev installs are now preserved across `install-daemon.sh` re-runs.

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

### Technical State (v1.11.1)

<details>
<summary><b>Benchmarks & Stability</b></summary>

- **Tests**: 502/502 passed (100% Green).
- **RAM Footprint**: ~340MB (Baseline) / ~650MB (Peak).
- **Search Latency**: ~20ms (Semantic) / ~5ms (Exact Time SQL).

</details>

<details>
<summary><b>Autonomous Mechanics (v1.11.0+)</b></summary>

- **Mechanism #12**: `PersistStep` now includes a `classify_session_type` call. Code/Research artifacts are automatically captured.
- **Exact Time**: `content_search` and `ctx_search` now support high-precision temporal windows.

</details>

---

### License

**FSL-1.1-MIT**  
Commercially restricted for the first 2 years, then MIT. For personal use - **free forever**.

---
**Generated:** 2026-05-03  
**v1.11.1** | 502 tests green | [Full Release Notes](./RELEASE_NOTES_v1.11.1.md)
