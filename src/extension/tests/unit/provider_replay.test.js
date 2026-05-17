import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import claude from '../../src/content/providers/claude.js';
import chatgpt from '../../src/content/providers/chatgpt.js';
import perplexity from '../../src/content/providers/perplexity.js';
import grok from '../../src/content/providers/grok.js';

function loadFixture(name) {
  const p = path.resolve(process.cwd(), 'tests/fixtures/providers', name);
  return JSON.parse(fs.readFileSync(p, 'utf-8'));
}

describe('provider replay fixtures', () => {
  it('replays claude SSE lines into finalized assistant text', () => {
    const lines = loadFixture('claude_sse_lines.json');
    const deltas = [];
    for (const line of lines) {
      const r = claude.parseDelta(line);
      if (r.textDelta) deltas.push(r.textDelta);
      if (r.done) break;
    }
    const f = claude.finalize({ deltas });
    expect(f.assistantText).toBe('Hello world');
    expect(f.confidence).toBeGreaterThanOrEqual(0.85);
  });

  it('replays chatgpt SSE lines into finalized assistant text', () => {
    const lines = loadFixture('chatgpt_sse_lines.json');
    const deltas = [];
    for (const line of lines) {
      const r = chatgpt.parseDelta(line);
      if (r.textDelta) deltas.push(r.textDelta);
      if (r.done) break;
    }
    const f = chatgpt.finalize({ deltas });
    expect(f.assistantText).toBe('Hi there');
  });

  it('classifies turn types for regenerate/edit/new', () => {
    expect(chatgpt.classifyTurn({ regenerate: true })).toBe('regenerate');
    expect(chatgpt.classifyTurn({ edit_resend: true })).toBe('edit_resend');
    expect(chatgpt.classifyTurn({})).toBe('new_turn');
  });

  it('returns structured drift/malformed codes', () => {
    expect(chatgpt.parseDelta('not-json').control.type).toBe('MALFORMED_CHUNK');
    expect(chatgpt.parseDelta('{"foo":1}').control.type).toBe('MISSING_FIELD');
  });

  it('replays perplexity SSE lines into finalized assistant text', () => {
    const lines = loadFixture('perplexity_sse_lines.json');
    const deltas = [];
    for (const line of lines) {
      const r = perplexity.parseDelta(line);
      if (r.textDelta) deltas.push(r.textDelta);
      if (r.done) break;
    }
    const f = perplexity.finalize({ deltas });
    expect(f.assistantText).toBe('Sure, here you go');
    expect(f.confidence).toBeGreaterThanOrEqual(0.85);
  });

  it('replays grok SSE lines into finalized assistant text', () => {
    const lines = loadFixture('grok_sse_lines.json');
    const deltas = [];
    for (const line of lines) {
      const r = grok.parseDelta(line);
      if (r.textDelta) deltas.push(r.textDelta);
      if (r.done) break;
    }
    const f = grok.finalize({ deltas });
    expect(f.assistantText).toBe('Hello from Grok');
    expect(f.confidence).toBeGreaterThanOrEqual(0.8);
  });
});
