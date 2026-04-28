# Mnemostroma v1.8.5 - Stability & Precision Release

![Version](https://img.shields.io/badge/version-1.8.5-blue)
![License](https://img.shields.io/badge/license-FSL--1.1--MIT-green)
![Tests](https://img.shields.io/badge/tests-457%20passed-brightgreen)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20win-lightgrey)

**Mnemostroma** is a local cognitive memory layer for AI agents. This release focuses on increasing extraction precision for decisions and improving system stability across all supported platforms.

---

### Key Features (Updated)

- **High-Precision Decisions**: New priority-aware NER logic ensures that project decisions and prohibitions are captured correctly even when overlapping with technology names.
- **Anchor Evaluation Tools**: Introducing `anchor_replay.py`, allowing developers to verify and tune anchor extraction logic against existing session data.
- **Improved Lifecycle Management**: Full integration of "zombie process" cleanup and refined systemd/launchd service handlers.
- **Dynamic Context Detection**: The pipeline now correctly identifies session sources (User vs Agent) to ensure accurate memory attribution.

---

### Quick Start

**Option A: Automatic (Recommended)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Manual Setup**

```bash
pip install "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma setup
mnemostroma service install
mnemostroma on
```

---

### Technical Details (v1.8.5)

<details>
<summary><b>View Benchmarks & Performance</b></summary>

- **Regression Tests**: 457/457 passed.

- **Decision Coverage**: Reached 33% precision on anchor extraction (from 0% in previous iterations).

- **RAM Footprint**: Stable at ~480MB (Baseline) / 750MB (Hard Limit).

- **Inference**: Optimized ONNX Runtime settings for Predictable RSS behavior.
  
  </details>

<details>
<summary><b>Detailed Changelog</b></summary>

- `feat(observer)`: Added `anchor_replay` tool for precision analysis.

- `feat(ner)`: Implemented priority mapping for HybridNER (Decisions > Tech Names).

- `fix(pipeline)`: Dynamic `SourceType` injection and explicit entity attachment.

- `fix(install)`: Resolved `NameError` in Conductor and fixed terminal-tethering issues.

- `chore`: Updated documentation for stable v1.8.5 rollout.
  
  </details>

---

### License

**FSL-1.1-MIT**
Commercially restricted for the first 2 years, then MIT. For personal use - **free forever**.

---

### Assets in this Release

- `QUICKSTART_v1.8.5.md`: Updated deployment guide.
- `SYSTEM_ASSESSMENT.md`: Updated technical system audit (requires review).
