# Quick Start — Mnemostroma v1.11.2

## 🧠 Autonomous Memory & Temporal Precision — Core Stability Hotfix

Mnemostroma v1.11.2 is a hotfix for a critical startup crash introduced in v1.11.1.
All v1.11.0 and v1.11.1 features are fully intact.

### What's fixed in v1.11.2

- Daemon no longer crashes with `NameError: name 'LogWriter' is not defined` on startup
  after a fresh install from GitHub. Any installation using `pip install` from the repo
  was affected.

### Key Features (inherited from v1.11.0+)

- **Autonomous Content Branch**: The system automatically detects code and research
  and persists it to the content branch — no manual `save_content` needed.
- **Temporal Search**: Surgical precision when looking for memory in specific time windows.
- **Minimized API**: A cleaner, more robust MCP interface focused on retrieval and action.
- **AutoBridgeWorker**: Background pre-computation for sub-50ms session handoffs.

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

**Upgrade from v1.11.1:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma off && mnemostroma on
```

---

### Technical State (v1.11.2)

<details>
<summary><b>Benchmarks & Stability</b></summary>

- **Tests**: 502/502 passed (100% Green).
- **RAM Footprint**: ~340 MB (Baseline) / ~650 MB (Peak).
- **Search Latency**: ~20ms (Semantic) / ~5ms (Exact Time SQL).

</details>

<details>
<summary><b>Autonomous Mechanics (v1.11.0+)</b></summary>

- **Mechanism #12**: `PersistStep` now includes a `classify_session_type` call. Code/Research
  artifacts are automatically captured.
- **Exact Time**: `content_search` and `ctx_search` now support high-precision temporal windows.

</details>

---

### License

**FSL-1.1-MIT**  
Commercially restricted for the first 2 years, then MIT. For personal use — **free forever**.

---
**Generated:** 2026-05-10  
**v1.11.2** | 502 tests green | [Full Release Notes](./RELEASE_NOTES_v1.11.2.md)
