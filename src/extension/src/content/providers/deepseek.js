import { makeParser, parseJsonSafe } from './base.js';

export default makeParser('deepseek', '1.0.0', {
  allowlist: {
    hostname: 'chat.deepseek.com',
    pathPrefix: '/api/v0/chat/',
    methods: ['POST'],
  },
  matchRequest(meta) {
    return meta.method === 'POST' && meta.url.includes('/chat/completions');
  },
  extractUserInput(requestText) {
    const parsed = parseJsonSafe(requestText);
    if (!parsed.ok) return null;
    
    // DeepSeek payload is typically { prompt: "..." } or { messages: [...] }
    if (typeof parsed.value?.prompt === 'string') return parsed.value.prompt;
    
    const msgs = parsed.value?.messages;
    if (!Array.isArray(msgs)) return null;
    const user = [...msgs].reverse().find((m) => m?.role === 'user');
    if (!user) return null;
    return user.content || null;
  },
  extractConversationId(_meta, payload) {
    return payload?.chat_session_id ?? payload?.conversation_id ?? null;
  },
  parseDelta(dataLine) {
    if (dataLine === '[DONE]') return { done: true };
    const parsed = parseJsonSafe(dataLine);
    if (!parsed.ok) return { control: { type: 'MALFORMED_CHUNK' } };
    
    const ev = parsed.value;
    
    // Extract reasoning content (DeepSeek R1 'thinking' process)
    const reasoning = ev?.choices?.[0]?.delta?.reasoning_content ?? '';
    const text = ev?.choices?.[0]?.delta?.content ?? '';
    
    // If there is reasoning, we append it. Mnemostroma can handle both, but usually we ignore thinking for memory, or we can just capture it.
    // Since we don't want memory to be polluted by thought processes, we might only return `text` if we want final memory.
    // But for a faithful transport log, we can emit both.
    // For now, we just emit `text` (or reasoning + text if we want everything).
    if (text) return { textDelta: text };
    
    // If it's pure reasoning, we can return nothing or a special block. We'll ignore reasoning for now to keep memory clean.
    if (reasoning) return { textDelta: '' };

    return { control: { type: ev?.choices ? 'SCHEMA_DRIFT' : 'MISSING_FIELD' } };
  },
  classifyTurn(payload = {}) {
    return 'new_turn'; // DeepSeek web might not explicitly flag regenerates in the same way, rely on DOM if needed
  },
  finalize(context) {
    const blocks = context?.blocks ?? [];
    const textBlocks = blocks.filter((b) => b?.type === 'text').map((b) => b?.text ?? '');
    const assistantText = textBlocks.length ? textBlocks.join('') : (context?.deltas ?? []).join('');
    const confidence = assistantText ? 0.9 : 0.5;
    const warnings = assistantText ? [] : ['MISSING_TEXT'];
    return { assistantText, confidence, warnings };
  },
});
