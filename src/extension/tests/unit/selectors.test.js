// tests/unit/selectors.test.js
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { getSelectors, checkSelector } from '../../src/shared/selectors.js';

vi.mock('../../src/shared/compat.js', () => ({
  default: {},
}));

afterEach(() => {
  vi.restoreAllMocks();
  sessionStorage.clear();
});

// ─── getSelectors — hardcoded fallback (remote fetch rejected) ────────────────

describe('getSelectors — hardcoded fallback', () => {
  beforeEach(() => {
    // _fetchRemote sends postMessage and waits for __mnemo_reply.
    // Simulate SW replying with ok: false → falls through to hardcoded.
    vi.spyOn(window, 'postMessage').mockImplementation((msg) => {
      if (msg?.__mnemo && msg.type === 'FETCH_SELECTORS') {
        setTimeout(() => {
          window.dispatchEvent(new MessageEvent('message', {
            source: window,
            origin: window.location.origin,
            data: { __mnemo_reply: true, id: msg.id, res: { ok: false } },
          }));
        }, 0);
      }
    });
  });

  it('returns hardcoded selectors for claude.ai', async () => {
    const s = await getSelectors('claude.ai');
    expect(s).toMatchObject({ responseContainer: expect.any(String), stopButton: expect.any(String) });
  });

  it('returns hardcoded selectors for chatgpt.com', async () => {
    expect((await getSelectors('chatgpt.com'))?.responseContainer).toBeTruthy();
  });

  it('returns hardcoded selectors for gemini.google.com', async () => {
    expect((await getSelectors('gemini.google.com'))?.responseContainer).toBeTruthy();
  });

  it('returns hardcoded selectors for deepseek.com', async () => {
    expect((await getSelectors('deepseek.com'))?.responseContainer).toBeTruthy();
  });

  it('returns hardcoded selectors for perplexity.ai', async () => {
    expect((await getSelectors('perplexity.ai'))?.responseContainer).toBeTruthy();
  });

  it('returns null for unknown hostname', async () => {
    expect(await getSelectors('unknown.com')).toBeNull();
  });
});

// ─── getSelectors — sessionStorage cache ─────────────────────────────────────

describe('getSelectors — cache hit', () => {
  it('returns cached selectors without calling postMessage', async () => {
    const cached = { 'claude.ai': { responseContainer: '.cached', stopButton: '.stop' } };
    sessionStorage.setItem('mnemo_selectors_cache', JSON.stringify({
      data: cached, timestamp: Date.now(),
    }));

    const spy = vi.spyOn(window, 'postMessage');
    const s = await getSelectors('claude.ai');
    expect(s?.responseContainer).toBe('.cached');
    expect(spy).not.toHaveBeenCalled();
  });

  it('ignores expired cache and proceeds to remote', async () => {
    const expired = { 'claude.ai': { responseContainer: '.old' } };
    sessionStorage.setItem('mnemo_selectors_cache', JSON.stringify({
      data: expired, timestamp: Date.now() - 90_000_000, // > 24h
    }));

    vi.spyOn(window, 'postMessage').mockImplementation((msg) => {
      if (msg?.__mnemo && msg.type === 'FETCH_SELECTORS') {
        setTimeout(() => {
          window.dispatchEvent(new MessageEvent('message', {
            source: window,
            origin: window.location.origin,
            data: { __mnemo_reply: true, id: msg.id, res: { ok: false } },
          }));
        }, 0);
      }
    });

    const s = await getSelectors('claude.ai');
    // Falls through to hardcoded (not old cache)
    expect(s?.responseContainer).not.toBe('.old');
  });
});

// ─── getSelectors — remote fetch success ─────────────────────────────────────

describe('getSelectors — remote success via SW', () => {
  it('returns remote selectors when SW responds ok', async () => {
    const remote = { 'claude.ai': { responseContainer: '.remote', stopButton: '.btn' } };
    vi.spyOn(window, 'postMessage').mockImplementation((msg) => {
      if (msg?.__mnemo && msg.type === 'FETCH_SELECTORS') {
        setTimeout(() => {
          window.dispatchEvent(new MessageEvent('message', {
            source: window,
            origin: window.location.origin,
            data: { __mnemo_reply: true, id: msg.id, res: { ok: true, data: remote } },
          }));
        }, 0);
      }
    });

    const s = await getSelectors('claude.ai');
    expect(s?.responseContainer).toBe('.remote');
  });
});

// ─── checkSelector ────────────────────────────────────────────────────────────

describe('checkSelector', () => {
  afterEach(() => { document.body.innerHTML = ''; });

  it('returns true when selector matches', async () => {
    document.body.innerHTML = '<div class="r">text</div>';
    expect(await checkSelector('claude.ai', '.r')).toBe(true);
  });

  it('returns false when selector matches nothing', async () => {
    document.body.innerHTML = '';
    expect(await checkSelector('claude.ai', '.missing')).toBe(false);
  });

  it('returns false for null selector', async () => {
    expect(await checkSelector('claude.ai', null)).toBe(false);
  });

  it('returns false for invalid selector without throwing', async () => {
    expect(await checkSelector('claude.ai', '###bad')).toBe(false);
  });
});
