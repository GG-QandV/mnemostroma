/**
 * Mnemostroma Node.js Integration Example
 * 
 * ARCHITECTURAL CONCEPT:
 * This script demonstrates the "Observer" pattern. 
 * - The Write Path (Observer) is fire-and-forget; it doesn't block your app's performance.
 * - The Read Path (Memory Retrieval) is fast and should be done before the LLM prompt.
 * 
 * Required: A running Mnemostroma sidecar (default port 8767).
 */

const http = require('http');
const https = require('https');

// --- CONFIGURATION ---
const MNEMO_HP_HOST = 'localhost';
const MNEMO_HP_PORT = 8767; // Mnemostroma Sidecar Proxy Port
const MNEMO_REQUEST_TIMEOUT = 2000; // 2s budget for memory retrieval

/**
 * BLOCK 1: Infrastructure Utility
 * Simple wrapper for HTTP POST that handles timeouts and prevents blocking.
 */
async function request(options, data = null) {
    return new Promise((resolve, reject) => {
        const client = options.port === 443 ? https : http;
        const req = client.request(options, (res) => {
            let body = '';
            res.setEncoding('utf-8');
            res.on('data', chunk => { body += chunk; });
            res.on('end', () => resolve({ statusCode: res.statusCode, body }));
        });

        req.on('error', reject);
        req.setTimeout(MNEMO_REQUEST_TIMEOUT, () => {
            req.destroy();
            reject(new Error('Request Timeout'));
        });

        if (data) req.write(JSON.stringify(data));
        req.end();
    });
}

/**
 * BLOCK 2: Write Path (The Observer Push)
 * 
 * In Mnemostroma, your app doesn't "save to database". It simply "speaks" to the 
 * Sidecar Proxy, which observes the conversation. This function simulates 
 * sending a message through the proxy so Mnemostroma can index it.
 * 
 * Pattern: Fire-and-forget. We don't 'await' the processing.
 */
function pushToMemory(role, content) {
    const payload = {
        model: "mnemostroma-observer-v1",
        messages: [{ role, content }]
    };

    const options = {
        hostname: MNEMO_HP_HOST,
        port: MNEMO_HP_PORT,
        path: '/v1/messages', // Standardized interception endpoint
        method: 'POST',
        headers: { 'Content-Type': 'application/json' }
    };

    // We do NOT return the promise to the main loop to avoid blocking UI/API.
    // The Sidecar handles the complex indexing (NER, Embedding, Persistence).
    request(options, payload).catch(err => {
        // Log locally if Sidecar is down, but don't crash the app.
        console.warn('[MNEMO] Sidecar not reachable for Write Path:', err.message);
    });
}

/**
 * BLOCK 3: Read Path (The Memory Retrieval)
 * 
 * Fetches the compressed context before sending a prompt to the LLM. 
 * This gives the agent continuity without needing manual context management.
 */
async function getMemoryContext(query) {
    const options = {
        hostname: MNEMO_HP_HOST,
        port: MNEMO_HP_PORT,
        path: `/v1/context?q=${encodeURIComponent(query)}&limit=3`,
        method: 'GET'
    };

    try {
        const result = await request(options);
        if (result.statusCode !== 200) return null;
        const data = JSON.parse(result.body);
        return data.context_block; // Compressed XML/Markdown memory block
    } catch (err) {
        console.warn('[MNEMO] Could not fetch memory context:', err.message);
        return null;
    }
}

/**
 * BLOCK 4: Integration Workflow (Golden Standard)
 */
async function main() {
    const userPrompt = "How should we refactor the storage layer?";
    
    console.log('--- Step 1: Memory Retrieval (Read Path) ---');
    // We pull memory BEFORE calling the real LLM.
    const context = await getMemoryContext(userPrompt);
    
    const finalPrompt = context 
        ? `${context}\n\nUser: ${userPrompt}` 
        : userPrompt;
    
    console.log('[PROMPT PREP] Context injected:', !!context);

    console.log('\n--- Step 2: Simulated LLM Call ---');
    const simulatedResponse = "We should focus on implementing the WAL2 mode in SQLite for better concurrency.";
    console.log('[LLM RESPONSE]', simulatedResponse);

    console.log('\n--- Step 3: Global Memory Sync (Write Path) ---');
    // IMPORTANT: Handled as fire-and-forget.
    pushToMemory('user', userPrompt);
    pushToMemory('assistant', simulatedResponse);
    
    console.log('[SUCCESS] Data pushed to Observer. Interaction complete.');
}

if (require.main === module) {
    main();
}

module.exports = { pushToMemory, getMemoryContext };

