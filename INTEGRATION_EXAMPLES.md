# Mnemostroma Integration Examples

**Version: 1.0 | Date: 2026-04-17**

---

## Overview

Mnemostroma can be integrated into any Python AI application to add persistent, evolving memory. This document shows practical examples for different use cases.

---

## 1. Basic Memory Capture (Standalone Python App)

### Use Case
You have a Python application (CLI, script, or framework) and want to capture conversation history into Mnemostroma.

### Example: Simple Chatbot

```python
import asyncio
from mnemostroma import Conductor, SystemContext

async def main():
    # Initialize Mnemostroma
    conductor = Conductor()
    await conductor.start()
    
    try:
        # Simulate a conversation loop
        while True:
            user_input = input("You: ")
            if user_input.lower() == "quit":
                break
            
            # Your LLM call here (pseudocode)
            # response = await your_llm.generate(user_input)
            response = f"Echo: {user_input}"
            
            print(f"Bot: {response}")
            
            # Capture this interaction in Mnemostroma
            transcript = {
                "messages": [
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": response}
                ]
            }
            await conductor.observe(transcript)
            
    finally:
        await conductor.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

### What Happens
1. Mnemostroma initializes the daemon and loads models
2. Each user message + bot response is captured via `observe()`
3. On shutdown, memory is persisted to SQLite with embeddings
4. Next session: Mnemostroma auto-loads context from memory

---

## 2. LLM Prompt Injection (Multi-Turn Conversations)

### Use Case
You want Mnemostroma's memory context injected into your LLM prompt automatically.

### Example: Claude Integration with Memory

```python
import asyncio
import anthropic
from mnemostroma import Conductor

async def main():
    conductor = Conductor()
    await conductor.start()
    
    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY
    
    # Get Mnemostroma's memory context for this user
    # This searches historical embeddings and returns relevant context
    memory_context = conductor.inject(user_id="user_123")
    
    # Build LLM prompt with memory context
    system_prompt = f"""You are a helpful assistant.

[MEMORY CONTEXT]
{memory_context}
[END MEMORY]

Use this context to understand the user's background, preferences, and history."""
    
    # User's current message
    user_message = "What were we discussing last week about the migration?"
    
    # Call Claude with memory context
    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=system_prompt,
        messages=[
            {"role": "user", "content": user_message}
        ]
    )
    
    result = response.content[0].text
    print(f"Claude: {result}")
    
    # Capture this exchange in memory
    await conductor.observe({
        "messages": [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": result}
        ]
    })
    
    await conductor.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

### Benefits
- **Context carryover**: Claude automatically remembers previous sessions
- **Zero configuration**: Mnemostroma handles embedding, storage, retrieval
- **Privacy**: Everything stays local (no cloud telemetry)

---

## 3. Custom Agent Framework Integration

### Use Case
You have a custom agent framework (tool-use loop) and want to capture its full execution history.

### Example: Agentic Loop with Tools

```python
import asyncio
from mnemostroma import Conductor

class CustomAgent:
    def __init__(self):
        self.conductor = Conductor()
        self.tools = {
            "search": self.search_db,
            "analyze": self.analyze_data,
        }
    
    async def setup(self):
        await self.conductor.start()
    
    async def think(self, query: str) -> str:
        """One iteration of agent reasoning."""
        # Get memory context to inform tool selection
        memory = self.conductor.inject()
        
        # Your agent logic here (simplified)
        if "database" in query:
            result = await self.tools["search"](query)
        else:
            result = await self.tools["analyze"](query)
        
        return result
    
    async def run_session(self, user_query: str):
        """Complete interaction: reasoning + memory capture."""
        # Agent execution
        agent_output = await self.think(user_query)
        
        # Capture full transcript
        transcript = {
            "user_input": user_query,
            "agent_reasoning": agent_output,
            "tools_used": ["search"],  # or ["analyze"], etc.
        }
        await self.conductor.observe(transcript)
        
        return agent_output
    
    async def shutdown(self):
        await self.conductor.shutdown()
    
    async def search_db(self, query: str) -> str:
        return f"Found in DB: {query}"
    
    async def analyze_data(self, query: str) -> str:
        return f"Analysis result: {query}"

async def main():
    agent = CustomAgent()
    await agent.setup()
    
    # Simulate multiple interactions
    queries = [
        "search for user 123 in database",
        "analyze the performance metrics",
    ]
    
    for q in queries:
        result = await agent.run_session(q)
        print(f"Agent: {result}\n")
    
    await agent.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 4. Server-Side Memory (FastAPI/Flask)

### Use Case
You have an API server where each endpoint needs context from previous requests.

### Example: FastAPI with Memory

```python
from fastapi import FastAPI
from mnemostroma import Conductor
import asyncio

app = FastAPI()
conductor = Conductor()

@app.on_event("startup")
async def startup():
    await conductor.start()

@app.on_event("shutdown")
async def shutdown():
    await conductor.shutdown()

@app.post("/chat")
async def chat(user_id: str, message: str):
    """Endpoint that uses memory across requests."""
    # Retrieve user's memory context
    memory = conductor.inject(user_id=user_id)
    
    # Your LLM call with memory context (pseudocode)
    # response = await llm.generate(message, context=memory)
    response = f"Response to: {message}"
    
    # Capture this exchange
    await conductor.observe({
        "user_id": user_id,
        "messages": [
            {"role": "user", "content": message},
            {"role": "assistant", "content": response}
        ]
    })
    
    return {"response": response}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

### Deployment Notes
- Mnemostroma runs in a daemon (background process)
- API server connects to daemon via MCP or direct socket
- Memory persists across server restarts
- No database migration needed (SQLite handles schema)

---

## 5. Batch Processing with Memory

### Use Case
You process many documents/conversations and want to remember patterns across batches.

### Example: Document Analysis Pipeline

```python
import asyncio
from mnemostroma import Conductor

async def analyze_documents(documents: list) -> list:
    """Process documents with evolving memory."""
    conductor = Conductor()
    await conductor.start()
    
    results = []
    
    for i, doc in enumerate(documents):
        # Get memory of previous documents
        context = conductor.inject()
        
        # Analyze this document in context of previous ones
        # (simplified; your analysis logic here)
        analysis = {
            "doc_id": i,
            "content": doc,
            "prior_context": context,
        }
        
        # Capture analysis for future batches
        await conductor.observe({
            "document": doc,
            "analysis": analysis
        })
        
        results.append(analysis)
        print(f"Analyzed document {i}")
    
    await conductor.shutdown()
    return results

# Usage
async def main():
    docs = [
        "Document 1 about ML models",
        "Document 2 about transformers",
        "Document 3 about inference optimization",
    ]
    
    results = await analyze_documents(docs)
    print(f"Processed {len(results)} documents")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 6. Testing with Memory Snapshots

### Use Case
You want to test agent behavior across multiple sessions, using snapshots of memory.

### Example: Unit Tests with Memory

```python
import pytest
import asyncio
from mnemostroma import Conductor

@pytest.fixture
async def conductor():
    """Provide a Conductor instance for tests."""
    c = Conductor()
    await c.start()
    yield c
    await c.shutdown()

@pytest.mark.asyncio
async def test_memory_persistence(conductor: Conductor):
    """Test that memory persists across 'sessions'."""
    # Session 1: Initial interaction
    await conductor.observe({
        "messages": [
            {"role": "user", "content": "I prefer Python over Java"},
        ]
    })
    
    # Session 2: Retrieve memory
    context = conductor.inject()
    assert "Python" in context or "java" in context.lower(), \
        "Memory should capture language preference"

@pytest.mark.asyncio
async def test_anchor_consistency(conductor: Conductor):
    """Test that hard-coded anchors are never forgotten."""
    # Set an anchor (hard constraint)
    anchor = {
        "type": "constraint",
        "value": "never use external APIs",
        "importance": "critical"
    }
    
    # Simulate many interactions
    for i in range(100):
        await conductor.observe({
            "messages": [{"role": "user", "content": f"request {i}"}]
        })
    
    # Anchor should still be in memory
    context = conductor.inject()
    assert "external API" in context.lower() or "API" in context, \
        "Critical anchors should never decay"
```

---

## 7. Multi-Session Debugging

### Use Case
You want to debug an agent's behavior across multiple sessions by reviewing what Mnemostroma remembers.

### Example: Memory Inspection

```python
import asyncio
from mnemostroma import Conductor

async def inspect_memory():
    """Inspect what Mnemostroma has learned."""
    conductor = Conductor()
    await conductor.start()
    
    # Get memory context (includes recent interactions + anchors)
    context = conductor.inject(user_id="debug_user")
    
    print("=== Current Memory ===")
    print(context)
    print()
    
    # You can also access raw storage for analysis
    # (if using SQLite directly)
    import sqlite3
    db_path = conductor.ctx.persistence.db_path
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Query recent interactions
    cursor.execute("""
        SELECT type, value, created_at FROM artifacts
        ORDER BY created_at DESC LIMIT 10
    """)
    
    print("=== Recent Artifacts ===")
    for row in cursor.fetchall():
        print(f"{row[0]}: {row[1]} (at {row[2]})")
    
    conn.close()
    await conductor.shutdown()

if __name__ == "__main__":
    asyncio.run(inspect_memory())
```

---

## Common Patterns

### Pattern 1: Memory-Aware Tool Selection

```python
async def choose_tool(query: str, conductor: Conductor) -> str:
    """Select the right tool based on memory."""
    context = conductor.inject()
    
    # Simple heuristic: if memory mentions "database", use search tool
    if "database" in context.lower():
        return "search_tool"
    elif "analysis" in context.lower():
        return "analysis_tool"
    else:
        return "default_tool"
```

### Pattern 2: Memory-Based Rate Limiting

```python
async def check_rate_limit(user_id: str, conductor: Conductor) -> bool:
    """Limit requests based on historical patterns."""
    context = conductor.inject(user_id=user_id)
    
    # If memory shows excessive requests, deny
    if "rate_limit_exceeded" in context.lower():
        return False
    
    return True
```

### Pattern 3: Context-Aware Error Handling

```python
async def handle_error(error: Exception, conductor: Conductor) -> str:
    """Generate helpful error messages using memory."""
    context = conductor.inject()
    
    # If user previously had this error, suggest remembered workaround
    if "workaround" in context.lower():
        return f"Error: {error}. (Hint: try the approach from last time)"
    
    return str(error)
```

---

## Performance Considerations

### Latency
- `conductor.inject()` — ~20ms (semantic search)
- `conductor.observe()` — async, ~100ms (embedding + insert)
- Models lazy-load on first use (~500ms)

### Memory Footprint
- **Baseline**: ~420 MB (daemon + models)
- **Per user**: ~10 KB (memory index)
- **SQLite**: ~1 MB per 10K interactions

### Scaling
- Single daemon supports 100+ concurrent users (via MCP)
- Sharding: Run multiple daemons on different ports for 1000+ users

---

## Troubleshooting

### "Daemon not running"
```python
# Check daemon status
import subprocess
result = subprocess.run(["mnemostroma", "status"], capture_output=True)
print(result.stdout.decode())

# Restart if needed
subprocess.run(["mnemostroma", "off"])
subprocess.run(["mnemostroma", "on"])
```

### "Memory not persisting"
- Ensure `observe()` is awaited (async)
- Check daemon logs: `mnemostroma logs --days 1`
- Verify SQLite permissions: `ls -la ~/.mnemostroma/logs.db`

### "Slow response times"
- Check Qdrant memory usage: `mnemostroma status`
- Reduce observation frequency if embedded in tight loops
- Consider running daemon on separate machine

---

## Next Steps

- **For MCP setup**: See [Connecting to LLM](../README.md#connecting-to-llm-mcp)
- **For API reference**: See [MCP_TOOLS_MAP.md](./MCP_TOOLS_MAP.md)
- **For architecture**: See [MEMORY_SPEC_v2.md](./MEMORY_SPEC_v2.md)

