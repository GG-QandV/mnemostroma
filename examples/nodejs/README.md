# Mnemostroma Node.js Integration

This example demonstrates how to integrate the **Mnemostroma Memory Sidecar** into a Node.js application using standard HTTP/HTTPS modules (zero external dependencies).

## Architectural Concept: The Observer Pattern

Unlike traditional RAG systems where you manually manage database writes, Mnemostroma uses an **Observer-only write path**. 

1.  **Read Path (Active)**: Before sending a prompt to your LLM, you "pull" relevant facts from the sidecar.
2.  **Write Path (Passive/Observer)**: After receiving an LLM response, you "push" the data to the sidecar proxy. This is non-blocking and fire-and-forget.

### Data Flow
```text
[Your App] -- (1) HTTP GET /v1/context?q=... --> [Mnemostroma Sidecar]
[Your App] <- (2) <memory_context> block --------- [Mnemostroma Sidecar]
    |
[Your App] -- (3) Final Prompt with Context ----> [LLM (OpenAI/Anthropic)]
[Your App] <- (4) LLM Response ------------------ [LLM (OpenAI/Anthropic)]
    |
[Your App] -- (5) HTTP POST /v1/messages --------> [Mnemostroma Sidecar]
              (Fire-and-forget push)              [Observer Pipeline]
                                                        ↓
                                                  [NER -> Embed -> WAL]
```

## How to use

### 1. Requirements
*   Node.js ≥ 16
*   Mnemostroma running locally (default: `localhost:8767`)

### 2. Running the example
```bash
node index.js
```

### 3. Running Validation
```bash
node test.js
```

## Implementation Details

### The Write Path (Observer)
The `pushToMemory` function in `index.js` uses a "fire-and-forget" pattern. It does not `await` the response from the sidecar, ensuring that your application's user experience is never slowed down by background memory indexing.

### Resilience
The example includes built-in timeouts and error handling. If the Mnemostroma sidecar is offline, the application will simply continue without memory enrichment rather than crashing (**Graceful Degradation**).

---
*For full protocol details, see [Mnemostroma MCP Documentation](https://github.com/GG-QandV/mnemostroma).*
