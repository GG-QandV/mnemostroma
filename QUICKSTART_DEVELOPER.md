# Developer Quick Start Guide

**Version: 1.0 | Date: 2026-04-17**

Get Mnemostroma running in your AI project in 15 minutes.

---

## Step 1: Install (2 min)

### Option A: As a Daemon (Recommended)

```bash
# Install via pipx (isolated environment)
pipx install mnemostroma

# Start daemon
mnemostroma on

# Verify it's running
mnemostroma status
```

### Option B: Development Mode

```bash
# Clone and install in editable mode
git clone https://github.com/GG-QandV/mnemostroma-core.git
cd mnemostroma
pip install -e ".[dev]"

# Start daemon
mnemostroma on
```

---

## Step 2: Add to Your Project (3 min)

### Install the Python Package

```bash
# If using mnemostroma as a library
pip install mnemostroma

# Or with optional dependencies
pip install "mnemostroma[sse]"  # For SSE (streaming)
```

---

## Step 3: Basic Usage (5 min)

### Minimal Example

```python
import asyncio
from mnemostroma import Conductor

async def main():
    conductor = Conductor()
    await conductor.start()
    
    try:
        # Your LLM interaction here
        user_input = "What should I build next?"
        
        # Get memory context (optional but recommended)
        context = conductor.inject()
        
        # Call your LLM with context
        # response = await llm.generate(user_input, context=context)
        response = f"Response to: {user_input}"
        
        # Capture this exchange in memory
        await conductor.observe({
            "messages": [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": response}
            ]
        })
        
        print(response)
        
    finally:
        await conductor.shutdown()

asyncio.run(main())
```

### What Happens

1. `Conductor().start()` — Loads models, connects to daemon
2. `conductor.inject()` — Retrieves relevant memories from previous sessions
3. `conductor.observe()` — Stores this interaction for future sessions
4. `conductor.shutdown()` — Flushes data, cleans up

**That's it!** Mnemostroma now remembers everything you capture with `observe()`.

---

## Step 4: Test It Works (3 min)

### Run the Example
```bash
# Create a test script
cat > test_memory.py << 'EOF'
import asyncio
from mnemostroma import Conductor

async def test():
    conductor = Conductor()
    await conductor.start()
    
    # Session 1: Capture a preference
    await conductor.observe({
        "messages": [{
            "role": "user",
            "content": "I prefer Python over Java"
        }]
    })
    print("✓ Captured: Python preference")
    
    # Session 2: Retrieve it
    context = conductor.inject()
    print(f"✓ Retrieved context: {context[:100]}...")
    
    await conductor.shutdown()

asyncio.run(test())
EOF

python test_memory.py
```

**Expected output:**
```
✓ Captured: Python preference
✓ Retrieved context: ...Python...
```

---

## Step 5: Connect to Your LLM (2 min)

### With Claude API

```python
import asyncio
import anthropic
from mnemostroma import Conductor

async def chat_with_claude(user_input: str):
    conductor = Conductor()
    await conductor.start()
    
    try:
        # Get memory context
        memory = conductor.inject()
        
        # Create Claude client
        client = anthropic.Anthropic()
        
        # Build prompt with memory
        system_prompt = f"""You are a helpful assistant.

[MEMORY FROM PREVIOUS SESSIONS]
{memory}
[END MEMORY]

Use this context to understand the user's background and preferences."""
        
        # Call Claude
        response = client.messages.create(
            model="claude-opus-4-7",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": user_input}]
        )
        
        result = response.content[0].text
        
        # Store this exchange in memory
        await conductor.observe({
            "messages": [
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": result}
            ]
        })
        
        return result
        
    finally:
        await conductor.shutdown()

# Usage
import asyncio
result = asyncio.run(chat_with_claude("What did I say I preferred last time?"))
print(result)
```

---

## Step 6: Choose Your Integration Pattern

### Pattern A: Standalone Script
Use when: Running one-off scripts, testing

```python
async def process_file(filename: str):
    conductor = Conductor()
    await conductor.start()
    try:
        # Your logic here
    finally:
        await conductor.shutdown()
```

### Pattern B: Long-Running Server (FastAPI)
Use when: Building an API service

```python
from fastapi import FastAPI
from mnemostroma import Conductor

app = FastAPI()
conductor = Conductor()

@app.on_event("startup")
async def startup():
    await conductor.start()

@app.on_event("shutdown")
async def shutdown():
    await conductor.shutdown()

@app.post("/chat")
async def chat(message: str):
    context = conductor.inject()
    # Your logic here...
    return {"response": "..."}
```

### Pattern C: Agent Loop
Use when: Building autonomous agents

```python
class MyAgent:
    def __init__(self):
        self.conductor = Conductor()
    
    async def run(self, user_query: str):
        await self.conductor.start()
        try:
            # Get memory to inform decisions
            context = self.conductor.inject()
            
            # Make a decision
            action = self.decide(user_query, context)
            
            # Execute and capture
            result = await self.execute(action)
            await self.conductor.observe({"action": action, "result": result})
            
            return result
        finally:
            await self.conductor.shutdown()
```

---

## Common Questions

### Q: Does Mnemostroma work offline?
**A:** Yes! Everything runs locally. No cloud calls, no telemetry.

---

### Q: How much does it cost?
**A:** Free. Open source (FSL-1.1-MIT license).

---

### Q: Can I share memory across users?
**A:** Yes, use `conductor.inject(user_id="user_123")` to scope memory per user.

---

### Q: How much memory does it use?
**A:** ~420 MB baseline (daemon + models). Add ~10 KB per user.

---

### Q: What LLMs does it support?
**A:** Any LLM API (Claude, OpenAI, Anthropic, local llama, etc.). Mnemostroma is LLM-agnostic.

---

### Q: How long does context stay in memory?
**A:** Indefinitely, but with "memory decay" (older items have lower retrieval priority). Hard anchors never decay.

---

## Next Steps

1. **Read**: [API_REFERENCE.md](./API_REFERENCE.md) for full method documentation
2. **Learn**: [INTEGRATION_EXAMPLES.md](./INTEGRATION_EXAMPLES.md) for 7 detailed examples
3. **Deploy**: [README.md#installation](../README.md#installation) for production setup
4. **Troubleshoot**: [README.md#logging](../README.md#logging) for debugging

---

## Gotchas & Tips

### ⚠️ Gotcha: Forgetting `await` on async methods
```python
# ❌ WRONG - This doesn't actually observe anything
conductor.observe(data)  # Missing await!

# ✅ RIGHT
await conductor.observe(data)
```

### ✅ Tip: Use context managers for cleanup
```python
# Better pattern with AsyncExitStack
from contextlib import AsyncExitStack

async with AsyncExitStack() as stack:
    conductor = Conductor()
    await stack.enter_async_context(conductor.start())
    # Automatically cleaned up on exit
```

### ✅ Tip: Batch observations for efficiency
```python
# Instead of observing one by one
for message in messages:
    await conductor.observe(message)  # Slow

# Do this
transcript = {"messages": messages}
await conductor.observe(transcript)  # Fast
```

---

## Troubleshooting

### "ModuleNotFoundError: No module named 'mnemostroma'"

**Fix:**
```bash
pip install mnemostroma
```

---

### "RuntimeError: Daemon not responding"

**Fix:**
```bash
mnemostroma status  # Check if running
mnemostroma on      # Start if not
mnemostroma logs    # Check for errors
```

---

### "Models not loading / slow startup"

**First run takes time (models download ~400MB):**
```bash
# Check progress
mnemostroma logs --days 1 | tail -20

# This is normal:
# Loading onnx models: 30-60s on first run
# Subsequent runs: 1-2s
```

---

## Performance Notes

| Metric | Value | Context |
|--------|-------|---------|
| Time to start | ~500ms | First run, lazy load |
| Time to get context | ~20ms | Semantic search |
| Time to capture | ~100ms | Async embedding |
| Memory per user | ~10 KB | Index overhead |

---

## What Mnemostroma Remembers

✅ **Captures:**
- Full conversation transcripts
- Named entities (people, places, organizations)
- Technical decisions & constraints
- Dates, timelines, dependencies
- User preferences & style
- Problem-solving patterns

❌ **Doesn't capture:**
- System prompts (by design)
- Large binary files
- Real-time sensor data
- Sensitive PII (you control what to observe)

---

## Support

- **Issues**: [GitHub Issues](https://github.com/GG-QandV/mnemostroma/issues)
- **Docs**: [Full Documentation](../README.md)
- **Examples**: [Integration Examples](./INTEGRATION_EXAMPLES.md)

