# Quick Start — Mnemostroma v2.0.5

## 🧠 Complete Browser Integration, SSE Transport & Security Release

Mnemostroma v2.0.5 is a major stable release that bridges the local memory layer with cloud-based AI environments (like `claude.ai`) and CLI terminals (like `Claude Code`) through an authenticated SSE transport and a highly robust browser extension.

### What's new in v2.0.5

- **Mnemostroma Browser Extension (v1.0.4)**: Automatically captures chat sessions in real-time from Claude, ChatGPT, Perplexity, Gemini, DeepSeek, and Grok.
- **Secure SSE Adapter (`mnemostroma sse`)**: Starts local ports for unified memory streaming:
  - `8765`: Authenticated MCP SSE endpoint for external integrations (e.g. `claude.ai`).
  - `8766`: Local unauthenticated port for the browser extension's DOM observer (localhost-only).
  - `8767`: Local TLS passthrough proxy for CLI clients (like `Claude Code`).
- **Release Guard Stability**: The browser extension runs with `IS_MCP_TUNNELING_ENABLED = false` by default for the public release, utilizing a 100% stable DOM-based observer to feed the local daemon seamlessly, while keeping the network interception footprint minimal.
- **Enhanced Token Security**: Automatic file permission enforcement (`chmod 0o600`) on generated tokens (`sse_token`, `observe_token`) to prevent unauthorized local file read access.

---

### Installation & Setup

**Option A: Automatic installation script (Linux/macOS)**

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**Option B: Windows (PowerShell)**

```powershell
powershell -ExecutionPolicy Bypass -Command "iwr https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/windows/install-daemon.ps1 -OutFile install-daemon.ps1; .\install-daemon.ps1"
```

**Upgrade existing installation:**

```bash
~/.mnemostroma/venv/bin/pip install --upgrade \
  "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma off && mnemostroma on
```

---

### 📢 CRITICAL NEXT STEP: Install the Browser Extension

To feed your chats from `claude.ai`, ChatGPT, Gemini, etc. into Mnemostroma:
1. Open `chrome://extensions` (or `about:debugging` in Firefox).
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select the directory: `/path/to/mnemostroma/src/extension/`

👉 For detailed, step-by-step setup (including Cloudflare Tunnel for cloud MCP), see:
* [INSTALL.md](../src/extension/docs/INSTALL.md)
* [CLAUDE_AI_SETUP.md](../docs/CLAUDE_AI_SETUP.md)

---

### Technical State (v2.0.5)

<details>
<summary><b>Benchmarks & Stability</b></summary>

- **Tests**: 531/531 passed (100% Green).
- **RAM Footprint**: ~340 MB (Baseline) / ~650 MB (Peak).
- **Search Latency**: ~20ms (Semantic) / ~5ms (Exact Time SQL).

</details>

<details>
<summary><b>Security & Ports</b></summary>

- **Authorization**: Mandatory Bearer token validation for the public SSE port (:8765).
- **Isolation**: Browser observer port (:8766) is bound to `127.0.0.1` and accepts only local traffic.
- **Credentials Security**: Automatically generates cryptographically secure url-safe tokens with strict `0600` file permissions.

</details>

---

### License

**FSL-1.1-MIT**  
Commercially restricted for the first 2 years, then MIT. For personal use — **free forever**.

---
**Generated:** 2026-05-17  
**v2.0.5** | 531 tests green | [Full Release Notes](./RELEASE_NOTES_v2.0.5.md)
