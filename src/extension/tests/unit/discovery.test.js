// tests/unit/discovery.test.js
import { describe, it, expect, vi, afterEach } from 'vitest';
import { checkSelector } from '../../src/shared/discovery.js';

vi.mock('../../src/shared/compat.js', () => ({
  default: {
    storage: {
      local: {
        get: vi.fn().mockResolvedValue({}),
        set: vi.fn().mockResolvedValue(undefined),
      },
    },
  },
}));

afterEach(() => {
  vi.restoreAllMocks();
  document.body.innerHTML = '';
});

describe('checkSelector', () => {
  it('returns true when selector matches element with text', async () => {
    document.body.innerHTML = '<div class="response">Hello world</div>';
    expect(await checkSelector('claude.ai', '.response')).toBe(true);
  });

  it('returns false when selector matches element with no text', async () => {
    document.body.innerHTML = '<div class="response">   </div>';
    expect(await checkSelector('claude.ai', '.response')).toBe(false);
  });

  it('returns false when selector matches nothing', async () => {
    document.body.innerHTML = '<div class="other">text</div>';
    expect(await checkSelector('claude.ai', '.response')).toBe(false);
  });

  it('returns false for null selector', async () => {
    expect(await checkSelector('claude.ai', null)).toBe(false);
  });

  it('returns false for empty string selector', async () => {
    expect(await checkSelector('claude.ai', '')).toBe(false);
  });

  it('returns false for invalid CSS selector without throwing', async () => {
    expect(await checkSelector('claude.ai', '###invalid')).toBe(false);
  });

  it('returns true for first matching element with text when multiple exist', async () => {
    document.body.innerHTML = `
      <div class="msg">first</div>
      <div class="msg">second</div>
    `;
    expect(await checkSelector('claude.ai', '.msg')).toBe(true);
  });
});
