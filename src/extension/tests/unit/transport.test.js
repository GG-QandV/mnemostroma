// tests/unit/transport.test.js — расширенный
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { postCollect } from '../../src/shared/transport.js';

beforeEach(() => {
  vi.stubGlobal('AbortSignal', {
    timeout: () => ({ aborted: false }),
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe('postCollect — success', () => {
  it('returns true on first successful response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
    expect(await postCollect({ test: 1 })).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('returns true on second attempt after first network failure', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockRejectedValueOnce(new Error('network'))
      .mockResolvedValueOnce({ ok: true, status: 200 })
    );
    expect(await postCollect({ test: 1 })).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('returns true on third attempt after two 5xx', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({ ok: false, status: 503 })
      .mockResolvedValueOnce({ ok: true,  status: 200 })
    );
    expect(await postCollect({ test: 1 })).toBe(true);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('sends correct Content-Type header', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
    await postCollect({ test: 1 });
    const callArgs = fetch.mock.calls[0][1];
    expect(callArgs.headers['Content-Type']).toBe('application/json');
  });

  it('serializes payload as JSON in body', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200 }));
    const payload = { session_id: 'abc', text: 'hello' };
    await postCollect(payload);
    const body = fetch.mock.calls[0][1].body;
    expect(JSON.parse(body)).toEqual(payload);
  });
});

describe('postCollect — failure', () => {
  it('returns false after all 3 attempts fail with network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('network')));
    expect(await postCollect({ test: 1 })).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('returns false immediately on 400 — no retry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 400 }));
    expect(await postCollect({ test: 1 })).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('returns false immediately on 422 — no retry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 422 }));
    expect(await postCollect({ test: 1 })).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('retries on 503 — exactly 3 times', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    expect(await postCollect({ test: 1 })).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('retries on 500 — exactly 3 times', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 500 }));
    expect(await postCollect({ test: 1 })).toBe(false);
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it('never throws on network error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('fatal')));
    await expect(postCollect({ test: 1 })).resolves.toBe(false);
  });

  it('never throws on 4xx', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));
    await expect(postCollect({ test: 1 })).resolves.toBe(false);
  });
});
