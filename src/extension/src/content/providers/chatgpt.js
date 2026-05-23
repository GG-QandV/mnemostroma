import { makeParser, parseJsonSafe } from './base.js';

export default makeParser('chatgpt', '1.0.0', {
  allowlist: {
    hostname: 'chatgpt.com',
    pathPrefix: '/backend-api/',
    methods: ['POST'],
  },
  matchRequest(meta) {
    return meta.method === 'POST' && (meta.url.includes('/backend-api/conversation') || meta.url.includes('/backend-api/f/conversation') || meta.url.includes('/v1/responses'));
  },
  extractUserInput(requestText) {
    const parsed = parseJsonSafe(requestText);
    if (!parsed.ok) return null;
    if (typeof parsed.value?.input === 'string') return parsed.value.input;
    const msgs = parsed.value?.messages;
    if (!Array.isArray(msgs)) return null;
    const user = [...msgs].reverse().find((m) => m?.role === 'user' || m?.author?.role === 'user');
    if (!user) return null;
    if (typeof user.content === 'string') return user.content;
    if (user.content?.parts && Array.isArray(user.content.parts)) return user.content.parts.join('\n');
    return null;
  },
  extractConversationId(_meta, payload) {
    return payload?.conversation_id ?? payload?.conversation?.id ?? null;
  },
  parseDelta(dataLine) {
    if (dataLine === '[DONE]') return { done: true };
    const parsed = parseJsonSafe(dataLine);
    if (!parsed.ok) return { control: { type: 'MALFORMED_CHUNK' } };
    const ev = parsed.value;
    const text = ev?.choices?.[0]?.delta?.content ?? '';
    if (text) return { textDelta: text };
    return { control: { type: ev?.choices ? 'SCHEMA_DRIFT' : 'MISSING_FIELD' } };
  },
  classifyTurn(payload = {}) {
    if (payload?.regenerate === true) return 'regenerate';
    if (payload?.edit_resend === true || payload?.edited === true) return 'edit_resend';
    return 'new_turn';
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
