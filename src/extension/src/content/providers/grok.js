import { makeParser, parseJsonSafe } from './base.js';

export default makeParser('grok', '1.0.0', {
  allowlist: {
    hostname: 'grok.com',
    pathPrefix: '/api/',
    methods: ['POST'],
  },
  matchRequest(meta) {
    return meta.method === 'POST' && (meta.url.includes('/chat/completions') || meta.url.includes('/v1/messages'));
  },
  extractUserInput(requestText) {
    const parsed = parseJsonSafe(requestText);
    if (!parsed.ok) return null;
    const msgs = parsed.value?.messages;
    if (!Array.isArray(msgs)) return null;
    const user = [...msgs].reverse().find((m) => m?.role === 'user');
    return typeof user?.content === 'string' ? user.content : null;
  },
  extractConversationId(_meta, payload) {
    return payload?.conversation_id ?? payload?.id ?? null;
  },
  parseDelta(dataLine) {
    if (dataLine === '[DONE]') return { done: true };
    const parsed = parseJsonSafe(dataLine);
    if (!parsed.ok) return { control: { type: 'MALFORMED_CHUNK' } };
    const ev = parsed.value;
    const text = ev?.choices?.[0]?.delta?.content ?? ev?.delta?.text ?? '';
    if (text) return { textDelta: text };
    return { control: { type: ev?.choices || ev?.delta ? 'SCHEMA_DRIFT' : 'MISSING_FIELD' } };
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
    const confidence = assistantText ? 0.86 : 0.5;
    const warnings = assistantText ? [] : ['MISSING_TEXT'];
    return { assistantText, confidence, warnings };
  },
});
