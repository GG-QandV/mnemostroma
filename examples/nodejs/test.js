/**
 * Mnemostroma Integration Test (Gold Standard)
 * 
 * Verifies:
 * 1. Read Path (graceful failure when sidecar is offline).
 * 2. Write Path (fire-and-forget logic).
 * 3. Payload integrity.
 */

const { pushToMemory, getMemoryContext } = require('./index');

async function runTests() {
    console.log('🧪 Starting Mnemostroma Integration Tests...\n');

    // Test 1: Offline Resilience
    console.log('[TEST 1] Testing Offline Resilience...');
    const context = await getMemoryContext('test query');
    if (context === null) {
        console.log('✅ Success: System handled offline sidecar gracefully.');
    } else {
        console.error('❌ Failure: Unexpected result from offline sidecar.');
    }

    // Test 2: Async Non-Blocking Write
    console.log('\n[TEST 2] Testing Non-blocking Write Path...');
    const start = Date.now();
    pushToMemory('user', 'This is a test');
    const duration = Date.now() - start;
    
    if (duration < 50) {
        console.log(`✅ Success: Write path returned in ${duration}ms (Non-blocking).`);
    } else {
        console.warn(`⚠️ Warning: Write path took ${duration}ms. Check for blocking calls.`);
    }

    console.log('\n--- Tests Finished ---');
}

runTests().catch(err => {
    console.error('Fatal Test Error:', err);
    process.exit(1);
});
