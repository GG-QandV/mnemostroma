import { describe, it, expect } from 'vitest';
import claude from '../../src/content/providers/claude.js';
import chatgpt from '../../src/content/providers/chatgpt.js';
import perplexity from '../../src/content/providers/perplexity.js';
import grok from '../../src/content/providers/grok.js';

function basicParserContract(parser) {
  expect(typeof parser.name).toBe('string');
  expect(typeof parser.version).toBe('string');
  expect(typeof parser.matchRequest).toBe('function');
  expect(typeof parser.extractUserInput).toBe('function');
  expect(typeof parser.extractConversationId).toBe('function');
  expect(typeof parser.parseDelta).toBe('function');
  expect(typeof parser.finalize).toBe('function');
}

describe('provider parser contract', () => {
  it('claude parser contract', () => basicParserContract(claude));
  it('chatgpt parser contract', () => basicParserContract(chatgpt));
  it('perplexity parser contract', () => basicParserContract(perplexity));
  it('grok parser contract', () => basicParserContract(grok));
});

describe('claude parser behavior', () => {
  it('matches anthropic messages endpoint', () => {
    expect(claude.matchRequest({ url: 'https://api.anthropic.com/v1/messages', method: 'POST' })).toBe(true);
  });

  it('extracts user input from messages[]', () => {
    const req = JSON.stringify({ messages: [{ role: 'user', content: 'hello' }] });
    expect(claude.extractUserInput(req)).toBe('hello');
  });

  it('parses text delta and done event', () => {
    const d = claude.parseDelta(JSON.stringify({ type: 'content_block_delta', delta: { type: 'text_delta', text: 'abc' } }));
    expect(d.textDelta).toBe('abc');
    const done = claude.parseDelta(JSON.stringify({ type: 'message_stop' }));
    expect(done.done).toBe(true);
  });

  it('handles malformed chunk', () => {
    const r = claude.parseDelta('not-json');
    expect(r.control?.type).toBe('MALFORMED_CHUNK');
  });
});

describe('chatgpt parser behavior', () => {
  it('chatgpt parses [DONE]', () => {
    expect(chatgpt.parseDelta('[DONE]').done).toBe(true);
  });
});

// ─── Perplexity — full 7-test suite ─────────────────────────────────────────

describe('perplexity parser — 7 required cases', () => {
  // 1. streaming happy path
  it('streaming happy path', () => {
    const r = perplexity.parseDelta(JSON.stringify({ choices: [{ delta: { content: 'px' } }] }));
    expect(r.textDelta).toBe('px');
  });

  // 2. non-stream path (finalize from accumulated deltas)
  it('non-stream finalize from deltas', () => {
    const f = perplexity.finalize({ deltas: ['a', 'b', 'c'] });
    expect(f.assistantText).toBe('abc');
    expect(f.confidence).toBeGreaterThan(0.5);
    expect(f.warnings).toHaveLength(0);
  });

  // 3. abort flow: [DONE] terminates
  it('abort flow — [DONE] returns done', () => {
    expect(perplexity.parseDelta('[DONE]').done).toBe(true);
  });

  // 4. schema drift
  it('schema drift returns SCHEMA_DRIFT', () => {
    const r = perplexity.parseDelta(JSON.stringify({ choices: [{ delta: { other: 1 } }] }));
    expect(r.control?.type).toBe('SCHEMA_DRIFT');
  });

  // 5. malformed chunk resilience
  it('malformed chunk returns MALFORMED_CHUNK', () => {
    expect(perplexity.parseDelta('not-json').control?.type).toBe('MALFORMED_CHUNK');
    expect(perplexity.parseDelta('').control?.type).toBe('MALFORMED_CHUNK');
  });

  // 6. confidence threshold behavior
  it('confidence low on empty finalize', () => {
    const f = perplexity.finalize({ deltas: [] });
    expect(f.confidence).toBeLessThanOrEqual(0.5);
    expect(f.warnings).toContain('MISSING_TEXT');
  });

  // 7. multipart normalization (blocks path)
  it('multipart blocks path in finalize', () => {
    const f = perplexity.finalize({ blocks: [{ type: 'text', text: 'block content' }] });
    expect(f.assistantText).toBe('block content');
    expect(f.confidence).toBeGreaterThan(0.5);
  });
});

// ─── Grok — full 7-test suite ────────────────────────────────────────────────

describe('grok parser — 7 required cases', () => {
  // 1. streaming happy path
  it('streaming happy path', () => {
    const r = grok.parseDelta(JSON.stringify({ choices: [{ delta: { content: 'gr' } }] }));
    expect(r.textDelta).toBe('gr');
  });

  // 2. non-stream path (finalize from accumulated deltas)
  it('non-stream finalize from deltas', () => {
    const f = grok.finalize({ deltas: ['a', 'b'] });
    expect(f.assistantText).toBe('ab');
    expect(f.confidence).toBeGreaterThanOrEqual(0.6);
    expect(f.warnings).toHaveLength(0);
  });

  // 3. abort flow: [DONE] terminates
  it('abort flow — [DONE] returns done', () => {
    expect(grok.parseDelta('[DONE]').done).toBe(true);
  });

  // 4. schema drift
  it('schema drift returns SCHEMA_DRIFT', () => {
    const r = grok.parseDelta(JSON.stringify({ choices: [{ delta: { other: 1 } }] }));
    expect(r.control?.type).toBe('SCHEMA_DRIFT');
  });

  // 5. malformed chunk resilience
  it('malformed chunk returns MALFORMED_CHUNK', () => {
    expect(grok.parseDelta('not-json').control?.type).toBe('MALFORMED_CHUNK');
    expect(grok.parseDelta('{bad').control?.type).toBe('MALFORMED_CHUNK');
  });

  // 6. confidence threshold behavior
  it('confidence low on empty finalize', () => {
    const f = grok.finalize({ deltas: [] });
    expect(f.confidence).toBeLessThanOrEqual(0.5);
    expect(f.warnings).toContain('MISSING_TEXT');
  });

  // 7. multipart normalization (blocks path)
  it('multipart blocks path in finalize', () => {
    const f = grok.finalize({ blocks: [{ type: 'text', text: 'grok block' }] });
    expect(f.assistantText).toBe('grok block');
    expect(f.confidence).toBeGreaterThan(0.5);
  });

  // Extra: extractUserInput and classifyTurn
  it('extracts user input from messages', () => {
    const req = JSON.stringify({ messages: [{ role: 'user', content: 'grok q' }] });
    expect(grok.extractUserInput(req)).toBe('grok q');
  });

  it('classifyTurn covers all variants', () => {
    expect(grok.classifyTurn({ regenerate: true })).toBe('regenerate');
    expect(grok.classifyTurn({ edit_resend: true })).toBe('edit_resend');
    expect(grok.classifyTurn({})).toBe('new_turn');
  });
});
