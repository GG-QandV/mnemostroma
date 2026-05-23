// tests/unit/adapters.test.js
import { describe, it, expect } from 'vitest';
import { extractChatId as claudeExtractChatId, extractUserMessage as claudeExtractUserMessage, extractLlmResponse as claudeExtractLlmResponse } from '../../src/content/adapters/claude.js';
import { extractChatId as chatgptExtractChatId, extractUserMessage as chatgptExtractUserMessage } from '../../src/content/adapters/chatgpt.js';
import { extractChatId as perplexityExtractChatId } from '../../src/content/adapters/perplexity.js';
import { extractChatId as deepseekExtractChatId } from '../../src/content/adapters/deepseek.js';
import { extractChatId as geminiExtractChatId, extractLlmResponse as geminiExtractLlmResponse } from '../../src/content/adapters/gemini.js';

// ─── claude.js ────────────────────────────────────────────────────────────────

describe('claude — extractChatId', () => {
  it('extracts id from /chat/{id}', () => {
    expect(claudeExtractChatId('https://claude.ai/chat/abc123')).toBe('abc123');
  });
  it('returns null for root url', () => {
    expect(claudeExtractChatId('https://claude.ai/')).toBeNull();
  });
  it('returns null for malformed url', () => {
    expect(claudeExtractChatId('not-a-url')).toBeNull();
  });
  it('handles hyphens and underscores', () => {
    expect(claudeExtractChatId('https://claude.ai/chat/abc_def-123')).toBe('abc_def-123');
  });
});

describe('claude — extractUserMessage', () => {
  it('returns last user message text', () => {
    document.body.innerHTML = `
      <div class="!font-user-message">first message</div>
      <div class="!font-user-message">last message</div>
    `;
    expect(claudeExtractUserMessage()).toBe('last message');
  });
  it('returns empty string when no elements', () => {
    document.body.innerHTML = '';
    expect(claudeExtractUserMessage()).toBe('');
  });
});

describe('claude — extractLlmResponse', () => {
  it('returns last response text', () => {
    document.body.innerHTML = `
      <div class="font-claude-message">first response</div>
      <div class="font-claude-message">last response</div>
    `;
    expect(claudeExtractLlmResponse('.font-claude-message')).toBe('last response');
  });
  it('returns empty string when selector matches nothing', () => {
    document.body.innerHTML = '';
    expect(claudeExtractLlmResponse('.font-claude-message')).toBe('');
  });
});

// ─── chatgpt.js ───────────────────────────────────────────────────────────────

describe('chatgpt — extractChatId', () => {
  it('extracts id from /c/{id}', () => {
    expect(chatgptExtractChatId('https://chatgpt.com/c/xyz-789')).toBe('xyz-789');
  });
  it('extracts id from GPT path /g/{gptId}/c/{id}', () => {
    expect(chatgptExtractChatId('https://chatgpt.com/g/g-abc/c/conv123')).toBe('conv123');
  });
  it('returns null for home page', () => {
    expect(chatgptExtractChatId('https://chatgpt.com/')).toBeNull();
  });
  it('returns null for malformed url', () => {
    expect(chatgptExtractChatId('bad-url')).toBeNull();
  });
});

describe('chatgpt — extractUserMessage', () => {
  it('returns text from .whitespace-pre-wrap child if present', () => {
    document.body.innerHTML = `
      <div data-message-author-role="user">
        <div class="whitespace-pre-wrap">hello world</div>
      </div>
    `;
    expect(chatgptExtractUserMessage()).toBe('hello world');
  });
  it('falls back to container text when no child', () => {
    document.body.innerHTML = `
      <div data-message-author-role="user">plain text</div>
    `;
    expect(chatgptExtractUserMessage()).toBe('plain text');
  });
  it('returns empty string when no elements', () => {
    document.body.innerHTML = '';
    expect(chatgptExtractUserMessage()).toBe('');
  });
});

// ─── perplexity.js ────────────────────────────────────────────────────────────

describe('perplexity — extractChatId', () => {
  it('extracts id from /search/{id}', () => {
    expect(perplexityExtractChatId('https://perplexity.ai/search/myquery123')).toBe('myquery123');
  });
  it('extracts id from /p/{slug}', () => {
    expect(perplexityExtractChatId('https://perplexity.ai/p/some-slug')).toBe('some-slug');
  });
  it('extracts id from /s/{shortId}', () => {
    expect(perplexityExtractChatId('https://perplexity.ai/s/abc')).toBe('abc');
  });
  it('returns null for root', () => {
    expect(perplexityExtractChatId('https://perplexity.ai/')).toBeNull();
  });
});

// ─── deepseek.js ──────────────────────────────────────────────────────────────

describe('deepseek — extractChatId', () => {
  it('extracts id from /chat/{id}', () => {
    expect(deepseekExtractChatId('https://deepseek.com/chat/ds456')).toBe('ds456');
  });
  it('returns null for /chat/new', () => {
    expect(deepseekExtractChatId('https://deepseek.com/chat/new')).toBeNull();
  });
  it('returns null for root', () => {
    expect(deepseekExtractChatId('https://deepseek.com/')).toBeNull();
  });
  it('returns null for malformed url', () => {
    expect(deepseekExtractChatId('bad')).toBeNull();
  });
});

// ─── gemini.js ────────────────────────────────────────────────────────────────

describe('gemini — extractChatId', () => {
  it('returns id from data-thread-id attribute', () => {
    document.body.innerHTML = '<div data-thread-id="thread-abc"></div>';
    expect(geminiExtractChatId('')).toBe('thread-abc');
  });
  it('returns id from data-conversation-id when thread-id absent', () => {
    document.body.innerHTML = '<div data-conversation-id="conv-xyz"></div>';
    expect(geminiExtractChatId('')).toBe('conv-xyz');
  });
  it('falls back to sessionStorage if no DOM attribute', () => {
    document.body.innerHTML = '';
    sessionStorage.setItem('mnemo_gemini_chat_id', 'stored-id');
    expect(geminiExtractChatId('')).toBe('stored-id');
    sessionStorage.removeItem('mnemo_gemini_chat_id');
  });
  it('generates UUID fallback when nothing available', () => {
    document.body.innerHTML = '';
    sessionStorage.removeItem('mnemo_gemini_chat_id');
    delete window.__mnemo_gemini_chat_id;
    const id = geminiExtractChatId('');
    expect(typeof id).toBe('string');
    expect(id.length).toBeGreaterThan(0);
  });
});

describe('gemini — extractLlmResponse', () => {
  it('skips empty elements, returns last non-empty', () => {
    document.body.innerHTML = `
      <div class="model-response-text"><p>first</p></div>
      <div class="model-response-text"></div>
      <div class="model-response-text"><p>last</p></div>
    `;
    // last element has content but middle is empty — returns last non-empty
    expect(geminiExtractLlmResponse('.model-response-text')).toBe('last');
  });
  it('returns empty string for empty selector match', () => {
    document.body.innerHTML = '';
    expect(geminiExtractLlmResponse('.model-response-text')).toBe('');
  });
});
