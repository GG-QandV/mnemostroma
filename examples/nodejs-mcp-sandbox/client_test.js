/**
 * Mnemostroma Client Test Simulator
 * 
 * ARCHITECTURE OVERVIEW:
 * This script demonstrates the "Observer" pattern and the "Zero-Guidance" injection concept.
 * Instead of forcing the agent to remember everything, Mnemostroma intercepts its communication
 * via the ConductorProxy and injects relevant memory blocks directly into the system prompt.
 */

const colors = {
    magenta: '\x1b[35m',
    yellow: '\x1b[33m',
    cyan: '\x1b[36m',
    reset: '\x1b[0m'
};

const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

function log(color, text) {
    console.log(`${color}${text}${colors.reset}`);
}

async function runTest() {
    // Step 1 — MCP Context Pull
    // Agents use ctx_semantic(query, top_n) to perform a RAG search over 
    // the RAM Index of sessions stored in SQLite. 
    log(colors.yellow, '[AGENT]       Calling MCP tool: ctx_semantic("refactor storage layer")');
    await sleep(600);
    log(colors.reset, '[MCP]         ctx_semantic() → searching RAM Index (205 sessions)...');
    await sleep(600);
    log(colors.reset, '[MCP]         → Found: 3 relevant sessions (scores: 0.87, 0.74, 0.69)');
    await sleep(600);
    log(colors.reset, '[MCP]         → Anchors: "decision: use WAL2 mode", "deadline: 2026-04-25"');
    await sleep(600);
    log(colors.yellow, '[AGENT]       Context received: <memory_context updated="2026-04-19">...</memory_context>');

    console.log('');

    // Step 2 — Prompt routed through Observer Proxy
    // All requests are routed through a local proxy. _extract_sse_text(chunk) 
    // parses the streaming response to feed the background memory pipeline.
    log(colors.yellow, '[AGENT]       Sending prompt via ANTHROPIC_BASE_URL=https://localhost:8767');
    await sleep(400);
    log(colors.cyan, '[OBSERVER]    → Intercepted: POST /v1/messages');
    await sleep(400);
    log(colors.cyan, '[OBSERVER]    → Extracted SSE text via _extract_sse_text(chunk)');
    await sleep(400);
    log(colors.cyan, '[OBSERVER]    → Calling observer_pipeline(text, session_id, ctx)');

    console.log('');

    // Step 3 — Pipeline internals (observer_pipeline in conductor.py)
    // The pipeline is high-speed and asynchronous. 
    // GLiNER.extract_entities() and EmbeddingEngine.aencode() run in parallel threads.
    log(colors.cyan, '[PIPELINE]    FilterStep.run()        →  0ms  (not duplicate)');
    await sleep(300);
    log(colors.cyan, '[PIPELINE]    NERStep.run()           → 12ms  GLiNER.extract_entities()');
    log(colors.cyan, '  entities: [{type:"technology", value:"SQLite WAL"}, {type:"decision", value:"use WAL2"}]');
    await sleep(300);
    log(colors.cyan, '[PIPELINE]    EmbedStep.run()         → 15ms  EmbeddingEngine.aencode()');
    log(colors.cyan, '  vector: fp16[384] computed');
    await sleep(300);
    log(colors.cyan, '[PIPELINE]    marker()                →  1ms  importance: "important"');
    await sleep(300);
    log(colors.cyan, '[PIPELINE]    PersistStep.run()       →  2ms');
    log(colors.cyan, '  → RAM Index: SessionBrief saved');
    log(colors.cyan, '  → persistence.enqueue_session(sb) → SQLite WAL async flush');
    await sleep(300);
    log(colors.cyan, '[PIPELINE]    Total: 30ms ✓  (budget: 40ms)');

    console.log('');

    // Step 4 — ConductorProxy injection
    // ConductorProxy.inject() builds a MemoryBlock from _build_static_cache() 
    // and semantic search results, providing the agent with context without manual guidance.
    log(colors.magenta, '[PROXY]       ConductorProxy.inject(user_message)');
    await sleep(500);
    log(colors.magenta, '[PROXY]       _build_static_cache() → decisions: 2, principles: 1, conflicts: 0');
    await sleep(500);
    log(colors.magenta, '[PROXY]       ctx_semantic(query, top_n=3) → <relevant> block ready');
    await sleep(500);
    log(colors.magenta, '[PROXY]       Injecting <memory_context> into system prompt');
    await sleep(500);
    log(colors.yellow, '[AGENT]       ✓ Next prompt carries full context. Zero guidance needed.');
}

runTest();
