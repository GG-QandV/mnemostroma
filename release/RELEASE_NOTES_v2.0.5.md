# Release Notes — Mnemostroma v2.0.5

## 🧠 Complete Browser Integration, SSE Transport & Security Stabilization

Mnemostroma v2.0.5 is a major stable release introducing dual-client support, live chat observation via a unified browser extension, and fully secure Server-Sent Events (SSE) adapters. This release establishes seamless integration between the local memory layer and cloud interfaces (such as `claude.ai`) as well as CLI companions (such as `Claude Code`).

---

### Key Features and Capabilities

#### 1. Mnemostroma Browser Extension (v1.0.4)
- **Live Memory Feeding**: Watches the DOM structure of your active web chat sessions and seamlessly streams messages to the local Mnemostroma daemon.
- **Universal Multi-Platform Support**: Out-of-the-box compatibility with **Claude**, **ChatGPT**, **Perplexity**, **Gemini**, **DeepSeek**, and **Grok**.
- **Release Guard Architecture**: Operates with `IS_MCP_TUNNELING_ENABLED = false` by default for the public channel, running in a 100% stable, low-overhead, and leak-proof DOM observation mode.

#### 2. Secure SSE Adapter Module (`mnemostroma sse`)
- **Dual-Client Connectivity**: Exposes unified network interfaces for various agents:
  - **Port 8765**: Public MCP SSE service. Allows cloud interfaces (e.g. `claude.ai` via Cloudflare Tunnel) to connect safely and request memory tools using explicit authorization tokens.
  - **Port 8766**: Local unauthenticated endpoint (`127.0.0.1` binding only) for high-speed local browser extension streaming.
  - **Port 8767**: Passthrough HTTPS proxy. Allows CLI terminals (like `Claude Code`) to connect using local self-signed TLS certificates.

#### 3. Strict Token & File System Security
- **Explicit Auth Enforcements**: Any generated security tokens (`sse_token`, `observe_token`) are locked down with strict POSIX file permissions (`chmod 0o600` / read-write only by owner) immediately upon creation, eliminating the risk of local multi-user token disclosure.

---

### Fixed and Resolved Issues

- **IPv6 Localhost Dropouts**: Replaced `localhost` with the explicit `127.0.0.1` binding in the extension's networking to avoid random connection drops caused by IPv6 lookup mismatches in modern browsers (Chrome/Edge).
- **SPA Noise in Logs**: Downgraded SPA-routing and page-load logs from `warn` to `debug`, reducing console noise and eliminating false alarms during heavy dynamic interface switches.
- **NameError in conductor.py**: Resolved a critical startup crash caused by a missing `LogWriter` import on fresh installations.
- **Documentation and Path Auditing**: Fixed several legacy paths (`browser_extension` and nested `/src/mnemostroma/extension/` errors) in `INSTALL.md` and `CLAUDE_AI_SETUP.md`, ensuring completely correct copy-paste instructions for unpacked plugin installations.

---

### Technical State & Test Coverage

- **Total Tests**: **531 passed** (up from 502). Complete validation of the new SSE, proxy, token validation, and multi-layered memory structures.
- **Regressions**: **0**.
- **RAM footprint**: Baseline ~340 MB, Peak ~650 MB.
- **Execution Latency**: Semantic retrieval: ~20ms, exact SQL searches: ~5ms.

---

### Upgrade Instructions

Please see [UPGRADE.md](../UPGRADE.md) $\rightarrow$ *Upgrading to v2.0.5*  
To configure the extension and Cloudflare Tunnel, follow [CLAUDE_AI_SETUP.md](../docs/CLAUDE_AI_SETUP.md).

---

**Generated:** 2026-05-17  
**Mnemostroma:** The offline-first memory layer for AI agents  
**v2.0.5** | 531 tests passing | 0 regressions | Major Integration & Security Release
