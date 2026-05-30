import { makeParser, parseJsonSafe } from './base.js';

export default makeParser('claude', '1.0.0', {
  allowlist: {
    hostname: 'claude.ai',
    pathPrefix: '/api/',
    methods: ['POST'],
  },
  matchRequest(meta) {
    return (meta.url.includes('/v1/messages') || meta.url.includes('/completion')) && meta.method === 'POST';
  },
  extractUserInput(requestText) {
    const parsed = parseJsonSafe(requestText);
    if (!parsed.ok) return null;
    
    const msgs = parsed.value?.messages || (parsed.value?.prompt ? [{role: 'user', content: parsed.value.prompt}] : null);
    if (!Array.isArray(msgs)) return null;
    const user = [...msgs].reverse().find((m) => m?.role === 'user');
    if (!user) return null;
    if (typeof user.content === 'string') return user.content;
    if (Array.isArray(user.content)) {
      return user.content.filter((x) => x?.type === 'text').map((x) => x?.text ?? '').join(' ').trim();
    }
    return null;
  },
  extractConversationId(_meta, payload) {
    return payload?.conversation_id ?? null;
  },
  parseDelta(dataLine) {
    const parsed = parseJsonSafe(dataLine);
    if (!parsed.ok) return { control: { type: 'MALFORMED_CHUNK' } };
    const ev = parsed.value;
    if (ev?.type === 'content_block_delta' && ev?.delta?.type === 'text_delta') {
      return { textDelta: ev.delta.text ?? '' };
    }
    if (ev?.type === 'completion') {
      return { textDelta: ev.completion ?? '' };
    }
    if (ev?.type === 'message_stop' || ev?.stop_reason || ev?.stop_sequence) return { done: true };
    return { control: { type: ev?.type ? 'SCHEMA_DRIFT' : 'MISSING_FIELD' } };
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
