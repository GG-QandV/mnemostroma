// tests/unit/session.test.js — расширенный
import { describe, it, expect } from 'vitest';
import {
  generateSessionId,
  generateExchangeId,
  generateRegenerateId,
  extractChatIdFromUrl,
  shortHostname,
} from '../../src/shared/session.js';

describe('shortHostname', () => {
  it('returns short form for claude.ai', () => {
    expect(shortHostname('claude.ai')).toBe('claude');
  });
  it('returns short form for gemini.google.com', () => {
    expect(shortHostname('gemini.google.com')).toBe('gemini');
  });
  it('returns original for unknown hostname', () => {
    expect(shortHostname('unknown.com')).toBe('unknown.com');
  });
  it('returns original for empty string', () => {
    expect(shortHostname('')).toBe('');
  });
});

describe('generateSessionId', () => {
  it('returns correct format', () => {
    const id = generateSessionId('claude.ai', 'abc123');
    expect(id).toMatch(/^browser-claude-abc123-\d+$/);
  });
  it('uses unix seconds not milliseconds', () => {
    const id = generateSessionId('claude.ai', 'abc');
    const ts = parseInt(id.split('-').at(-1));
    expect(ts).toBeLessThan(1e12); // seconds, not ms
  });
  it('two calls in same second produce same timestamp prefix', () => {
    const id1 = generateSessionId('claude.ai', 'abc');
    const id2 = generateSessionId('claude.ai', 'abc');
    const ts1 = id1.split('-').at(-1);
    const ts2 = id2.split('-').at(-1);
    expect(ts1).toBe(ts2); // known limitation — documented
  });
  it('different hostnames produce different session ids', () => {
    const id1 = generateSessionId('claude.ai', 'abc');
    const id2 = generateSessionId('chatgpt.com', 'abc');
    expect(id1).not.toBe(id2);
  });
  it('uses short hostname form', () => {
    const id = generateSessionId('gemini.google.com', 'xyz');
    expect(id).toContain('gemini');
    expect(id).not.toContain('google.com');
  });
});

describe('generateExchangeId', () => {
  it('appends counter to session id', () => {
    expect(generateExchangeId('browser-claude-abc-1000', 3))
      .toBe('browser-claude-abc-1000-3');
  });
  it('counter 1 produces correct id', () => {
    expect(generateExchangeId('s', 1)).toBe('s-1');
  });
  it('counter 0 is valid', () => {
    expect(generateExchangeId('s', 0)).toBe('s-0');
  });
  it('large counter works', () => {
    expect(generateExchangeId('s', 999)).toBe('s-999');
  });
});

describe('generateRegenerateId', () => {
  it('appends counter and retry suffix', () => {
    expect(generateRegenerateId('browser-claude-abc-1000', 2, 1))
      .toBe('browser-claude-abc-1000-2-r1');
  });
  it('second regenerate increments n', () => {
    expect(generateRegenerateId('s', 1, 2)).toBe('s-1-r2');
  });
  it('exchange counter unchanged between regenerates', () => {
    const r1 = generateRegenerateId('s', 3, 1);
    const r2 = generateRegenerateId('s', 3, 2);
    expect(r1).toBe('s-3-r1');
    expect(r2).toBe('s-3-r2');
  });
});

describe('extractChatIdFromUrl', () => {
  it('extracts chat_id from claude.ai', () => {
    expect(extractChatIdFromUrl('https://claude.ai/chat/abc123def', 'claude.ai'))
      .toBe('abc123def');
  });
  it('extracts chat_id from chatgpt.com', () => {
    expect(extractChatIdFromUrl('https://chatgpt.com/c/xyz-789', 'chatgpt.com'))
      .toBe('xyz-789');
  });
  it('extracts chat_id from perplexity.ai', () => {
    expect(extractChatIdFromUrl('https://perplexity.ai/search/myquery123', 'perplexity.ai'))
      .toBe('myquery123');
  });
  it('extracts chat_id from deepseek.com', () => {
    expect(extractChatIdFromUrl('https://deepseek.com/chat/ds456', 'deepseek.com'))
      .toBe('ds456');
  });
  it('returns null for gemini — no chat_id in URL', () => {
    expect(extractChatIdFromUrl('https://gemini.google.com/app', 'gemini.google.com'))
      .toBeNull();
  });
  it('returns null for unknown hostname', () => {
    expect(extractChatIdFromUrl('https://unknown.com/chat/abc', 'unknown.com'))
      .toBeNull();
  });
  it('returns null for malformed URL', () => {
    expect(extractChatIdFromUrl('not-a-url', 'claude.ai')).toBeNull();
  });
  it('returns null when path matches pattern but no id segment', () => {
    expect(extractChatIdFromUrl('https://claude.ai/chat/', 'claude.ai')).toBeNull();
  });
  it('ignores query params — extracts only path segment', () => {
    const id = extractChatIdFromUrl('https://claude.ai/chat/abc123?ref=test', 'claude.ai');
    expect(id).toBe('abc123');
  });
  it('handles chat_id with underscores and hyphens', () => {
    expect(extractChatIdFromUrl('https://chatgpt.com/c/abc_def-123', 'chatgpt.com'))
      .toBe('abc_def-123');
  });
});
