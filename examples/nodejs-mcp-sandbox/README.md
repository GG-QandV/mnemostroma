# Mnemostroma Node.js Sandbox

Interactive simulation of Mnemostroma's memory architecture — no installation required.

## Architecture Flow
```text
LLM Response → [Observer Proxy :8767] → observer_pipeline()
                    ↓                        ↓
            [SQLite WAL flush]    NERStep → EmbedStep → PersistStep
                    ↓                                  
            [MCP ctx_semantic]  ←  Agent requests context
                    ↓
            ConductorProxy.inject() → <memory_context> in system prompt
```

## How to run
1. Start the simulation environment:
   ```bash
   node sandbox_simulator.js
   ```
2. In a new terminal, run the agent test:
   ```bash
   node client_test.js
   ```

## Simulated vs Real
| This sandbox | Real Mnemostroma |
| :--- | :--- |
| console.log proxy | proxy_passthrough.py (Starlette ASGI) |
| mock NER entities | GLiNER ONNX INT8, ~12ms, ~60MB |
| mock embedding | multilingual-e5-small INT8, fp16[384] |
| mock SQLite flush | aiosqlite WAL2, async batch writer |
| mock MCP response | mcp_server.py stdio JSON-RPC |

Full architecture: https://github.com/GG-QandV/mnemostroma
