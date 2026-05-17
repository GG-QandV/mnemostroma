import { describe, it, expect, vi } from 'vitest';
import {
  buildRequestId,
  validateTransportEvent,
  createTransportCapture,
} from '../../src/content/transport_capture.js';

describe('transport_capture core', () => {
  it('buildRequestId is deterministic for same inputs', () => {
    const a = buildRequestId({ provider: 'chatgpt', method: 'POST', canonicalPath: '/v1/messages', tabId: '1', navEpoch: 3, seq: 7 });
    const b = buildRequestId({ provider: 'chatgpt', method: 'POST', canonicalPath: '/v1/messages', tabId: '1', navEpoch: 3, seq: 7 });
    expect(a).toBe(b);
  });

  it('rejects unknown event types', () => {
    expect(validateTransportEvent({ event_type: 'request_start' })).toBe(true);
    expect(validateTransportEvent({ event_type: 'weird_event' })).toBe(false);
    expect(validateTransportEvent(null)).toBe(false);
  });

  it('completes happy-path state transitions', () => {
    const finalized = vi.fn();
    const core = createTransportCapture({ onFinalized: finalized, provider: 'claude' });
    const id = core.startRequest({ method: 'POST', canonicalPath: '/v1/messages' });
    expect(core.getState(id)).toBe('REQUEST_STARTED');

    core.addUserInput(id, 'hello');
    const delta = core.addAssistantDelta(id, 'world');
    expect(delta.ok).toBe(true);
    expect(core.getState(id)).toBe('STREAMING');

    expect(core.doneRequest(id)).toBe(true);
    expect(finalized).toHaveBeenCalledTimes(1);
    const payload = finalized.mock.calls[0][0];
    expect(payload.capture_source).toBe('transport');
    expect(payload.userText).toBe('hello');
    expect(payload.assistantText).toBe('world');
  });

  it('drops stale chunk when nav epoch mismatches', () => {
    const metric = vi.fn();
    const core = createTransportCapture({ onMetric: metric, provider: 'perplexity' });
    const id = core.startRequest({});
    const res = core.addAssistantDelta(id, 'x', 999); // stale
    expect(res.ok).toBe(false);
    expect(res.reason).toBe('stale_chunk');
    expect(metric).toHaveBeenCalledWith('stale_chunk_drop');
  });

  it('fails request on first delta timeout', async () => {
    const metric = vi.fn();
    const core = createTransportCapture({
      onMetric: metric,
      timeoutOverrides: { first_delta_timeout_ms: 1 },
    });
    const id = core.startRequest({});
    await new Promise(r => setTimeout(r, 10));
    expect(core.getState(id)).toBe(null);
    expect(metric).toHaveBeenCalled();
  });
});
