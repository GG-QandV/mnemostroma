/** Malformed input fuzz checks (Security spec §6 requirement). */

import { describe, it, expect } from 'vitest';
import claude from '../../src/content/providers/claude.js';
import chatgpt from '../../src/content/providers/chatgpt.js';
import perplexity from '../../src/content/providers/perplexity.js';
import grok from '../../src/content/providers/grok.js';

const PARSERS = [claude, chatgpt, perplexity, grok];

const FUZZ_DELTA_INPUTS = [
  '',
  ' ',
  'null',
  'undefined',
  '{}',
  '[]',
  '{bad json',
  '{"type":null}',
  '{"choices":null}',
  '{"choices":[null]}',
  '{"choices":[{"delta":null}]}',
  '{"delta":{"text":null}}',
  'a'.repeat(100_000),
  '\x00\x01\x02',
  '{"type":"message_stop","delta":{"injected":"</script>"}}',
];

const FUZZ_REQUEST_INPUTS = [
  '',
  'null',
  '{}',
  '{"messages":null}',
  '{"messages":[]}',
  '{"messages":[{"role":null}]}',
  '{"messages":[{"role":"user","content":null}]}',
  '[]',
  '{bad',
];

describe('provider fuzz — parseDelta never throws', () => {
  for (const parser of PARSERS) {
    for (const input of FUZZ_DELTA_INPUTS) {
      it(`${parser.name}.parseDelta(${JSON.stringify(input).slice(0, 40)})`, () => {
        let result;
        expect(() => { result = parser.parseDelta(input); }).not.toThrow();
        // Must return an object with at least one of: textDelta, done, control
        expect(result).toBeDefined();
        expect(typeof result).toBe('object');
      });
    }
  }
});

describe('provider fuzz — extractUserInput never throws', () => {
  for (const parser of PARSERS) {
    for (const input of FUZZ_REQUEST_INPUTS) {
      it(`${parser.name}.extractUserInput(${JSON.stringify(input).slice(0, 40)})`, () => {
        let result;
        expect(() => { result = parser.extractUserInput(input); }).not.toThrow();
        // Must return null or string
        expect(result === null || typeof result === 'string').toBe(true);
      });
    }
  }
});

describe('provider fuzz — finalize never throws', () => {
  const fuzzContexts = [
    undefined,
    null,
    {},
    { deltas: null },
    { deltas: [null, undefined, 42, ''] },
    { blocks: null },
    { blocks: [null, { type: null }, { type: 'text', text: null }] },
    { deltas: [], blocks: [] },
  ];

  for (const parser of PARSERS) {
    for (const ctx of fuzzContexts) {
      it(`${parser.name}.finalize(${JSON.stringify(ctx)?.slice(0, 40)})`, () => {
        let result;
        expect(() => { result = parser.finalize(ctx); }).not.toThrow();
        expect(result).toBeDefined();
        expect(typeof result.assistantText).toBe('string');
        expect(typeof result.confidence).toBe('number');
        expect(Array.isArray(result.warnings)).toBe(true);
      });
    }
  }
});

describe('isAllowed — allowlist enforcement', () => {
  it('rejects wrong hostname', async () => {
    const { isAllowed } = await import('../../src/content/providers/base.js');
    expect(isAllowed(claude, { url: 'https://evil.com/api/append_message', method: 'POST' })).toBe(false);
  });

  it('rejects wrong method', async () => {
    const { isAllowed } = await import('../../src/content/providers/base.js');
    expect(isAllowed(chatgpt, { url: 'https://chatgpt.com/backend-api/conversation', method: 'GET' })).toBe(false);
  });

  it('accepts valid allowlist match', async () => {
    const { isAllowed } = await import('../../src/content/providers/base.js');
    expect(isAllowed(claude, { url: 'https://claude.ai/api/append_message', method: 'POST' })).toBe(true);
  });
});
