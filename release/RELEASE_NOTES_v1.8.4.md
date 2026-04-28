# Mnemostroma v1.8.4 - First Stable Release

![Version](https://img.shields.io/badge/version-1.8.4-blue)
![License](https://img.shields.io/badge/license-FSL--1.1--MIT-green)
![Tests](https://img.shields.io/badge/tests-450%20passed-brightgreen)
![Platform](https://img.shields.io/badge/platform-linux%20%7C%20macos%20%7C%20win-lightgrey)

**Mnemostroma** is a local cognitive memory layer for AI agents. It captures decisions, constraints, and important facts automatically, bringing them back to context exactly when they are needed.

---

### Key Features

- **Offline-first**: Your data never leaves your device.
- **Observer Pipeline**: Automatic, passive session context capture.
- **Structured Retrieval**: Semantic Search + Exact Anchors + Precision Facts.
- **Agent Protocol**: Enforced instruction injection via `<agent_protocol>` in every context.
- **Graceful Dissolution**: Smart RAM management: old/unimportant data transitions smoothly to SQLite archive.

---

### Quick Start

**Option A: Automatic (Recommended)**
One command. Creates venv, installs everything, configures systemd.

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: pipx (Ubuntu / Debian / Fedora)**
If your system blocks `pip install` (PEP 668):

```bash
sudo apt install pipx && pipx ensurepath
pipx install "git+https://github.com/GG-QandV/mnemostroma.git[all]"
mnemostroma setup
bash scripts/install-daemon.sh
```

**Start the Daemon:**

```bash
mnemostroma on
mnemostroma status
```

---

### Technical Details (v1.8.4)

<details>
<summary><b>View Benchmarks & Performance</b></summary>

- **Regression Tests**: 450/450 passed (including eviction loop fixes).

- **RAM Footprint**: 420MB (Idle) - 750MB (Peak).

- **Search Latency**: ~20ms for index of 10,000+ vectors.
  
  </details>

<details>
<summary><b>Changelog</b></summary>

- `feat(proxy)`: Injected `PROTOCOL_BLOCK` as the first element of memory context.

- `fix(dissolver)`: Resolved aggressive eviction loops during low RAM usage.

- `fix(ui)`: Restored system tray auto-start via `systemd --user`.

- `refactor`: Full internal log stripping for public release compliance.
  
  </details>

---

### License

**FSL-1.1-MIT**
Commercially restricted for the first 2 years to protect innovation, after which this version automatically transitions to the MIT license. For personal use - **free forever**.

---

### Assets in this Release

- `QUICKSTART_v1.8.4.md`: Rapid deployment guide.
- `SYSTEM_ASSESSMENT.md`: Full technical system audit.
