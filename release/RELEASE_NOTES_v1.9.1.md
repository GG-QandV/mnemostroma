# Mnemostroma v1.9.1 - The "Full Parity & Handoff" Release

![Version](https://img.shields.io/badge/version-1.9.1-blue)
![License](https://img.shields.io/badge/license-FSL--1.1--MIT-green)
![Tests](https://img.shields.io/badge/tests-467%20passed-brightgreen)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20win-lightgrey)

**Mnemostroma** is a local cognitive memory layer for AI agents. The `v1.9.1` release introduces true cross-platform parity for background services and the highly anticipated `AutoBridgeWorker` for autonomous AI context handoffs.

---

### Key Features

- **AutoBridge (L5 Subconscious)**: The system now automatically wakes up during idle periods to generate structured "Context Bridges". This enables seamless handoffs between different AI agents without losing the thread of the current task.
- **True Cross-Platform Installers**:
  - **Windows**: Full deployment of Daemon, Proxy, and Watchdog via Task Scheduler. No more manual `pip install` or tethered terminals.
  - **macOS**: Modernized `launchctl bootstrap` integration. All 3 agents (Daemon, Proxy, Watchdog) now run natively in the background via proper `.plist` files.
  - **Linux**: Streamlined systemd integration with automatic fallback detection for `pyenv` and `conda`.
- **Zero-Touch Provisioning**: All platform installers now automatically download the required ONNX models during setup.

---

### Quick Start

**Option A: Automatic (Recommended for Linux/macOS)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/windows/install-daemon.ps1 -OutFile install-daemon.ps1; .\install-daemon.ps1"
```

---

### Technical Details (v1.9.1)

<details>
<summary><b>View Benchmarks & Performance</b></summary>

- **Regression Tests**: 467/467 passed (Green Build).
- **RAM Footprint**: Idle footprint ~340MB (Daemon + Proxy + Watchdog combined).
- **Handoff Latency**: `ctx_bridge` now executes in under 50ms due to asynchronous pre-computation by `AutoBridgeWorker`.

</details>

<details>
<summary><b>Detailed Changelog</b></summary>

- `feat(autobridge)`: `AutoBridgeWorker` — autonomous background context bridge generation for seamless AI agent handoffs (L5).
- `feat(windows)`: Full Windows feature-parity installer with Proxy and Watchdog via Task Scheduler.
- `feat(macos)`: Full macOS feature-parity with native `launchctl bootstrap` and multi-agent Proxy/Watchdog `.plist` injection.
- `feat(installer)`: All platforms now auto-download ONNX models during `setup` or service installation.
- `fix(linux)`: `mnemostroma-sse` is now correctly enabled by `install.sh`.
- `fix(linux)`: Improved Python detector fallback for pyenv/conda and fixed `clean-zombies` invocation edge cases.
- `fix(cli)`: `update.sh` and `mnemo-health.sh` now correctly track and reset `mnemostroma-ui` and `mnemostroma-sse`.

</details>

---

### License

**FSL-1.1-MIT**
Commercially restricted for the first 2 years, then MIT. For personal use - **free forever**.
