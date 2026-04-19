# Mnemostroma Examples

Welcome to the examples directory. This folder contains different ways to understand, test, and integrate the Mnemostroma memory layer into your applications.

## 📂 Directory Structure

### 1. [Node.js Standard Integration](./nodejs/)
**Purpose:** Real-world production template.
- **Goal:** Demonstrate how a developer interacts with the Mnemostroma sidecar via HTTP/HTTPS.
- **Key Concepts:**
    - **Read Path:** Pulling memory context before the LLM prompt.
    - **Write Path:** Non-blocking "Observer" push for conversational data.
    - **Resilience:** Graceful degradation if the sidecar is offline.
- **Usage:** Ideal for building actual applications on top of Mnemostroma.

### 2. [Node.js Architecture Sandbox](./nodejs-mcp-sandbox/)
**Purpose:** Conceptual study and visualization.
- **Goal:** Simulate the internal "guts" of Mnemostroma without needing the actual system installed.
- **Key Concepts:**
    - **Conductor:** Orchestration of Proxy and MCP servers.
    - **Background Pipeline:** Visualization of NER (Named Entity Recognition), Embedding, and WAL (Write-Ahead Log) flushing.
    - **ConductorProxy:** Memory injection logic.
- **Usage:** Ideal for developers who want to understand *how* Mnemostroma processes data internally.

---

## Which one should I use?

*   If you are **building an app** and want to connect it to Mnemostroma: Use [**./nodejs/**](./nodejs/).
*   If you are **studying the code** and want to see the architecture in action: Use [**./nodejs-mcp-sandbox/**](./nodejs-mcp-sandbox/).

---
*Main repository: [Mnemostroma Core](https://github.com/GG-QandV/mnemostroma)*
