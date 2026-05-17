/** DOM-break resilience suite (Phase 4 — SPEC_capture_rollout_gates_v1.0 §5). */

import { describe, it, expect, vi } from 'vitest';
import { createTransportCapture } from '../../src/content/transport_capture.js';

describe('DOM-break resilience', () => {
  it('transport capture fires onFinalized even when DOM is not available', async () => {
    const finalized = vi.fn();
    const core = createTransportCapture({
      provider: 'claude',
      tabId: 'tab0',
      onFinalized: finalized,
      onMetric: () => {},
    });

    // Simulate a complete exchange via transport (DOM not involved)
    const reqId = core.startRequest({ url: 'https://claude.ai/api/append_message', method: 'POST' });
    core.addUserInput(reqId, 'hello');
    core.addAssistantDelta(reqId, 'Hi');
    core.addAssistantDelta(reqId, ' there');
    core.doneRequest(reqId);

    expect(finalized).toHaveBeenCalledOnce();
    const call = finalized.mock.calls[0][0];
    expect(call.assistantText).toBe('Hi there');
    expect(call.userText).toBe('hello');
  });

  it('stale chunks after nav_epoch change are dropped', () => {
    const finalized = vi.fn();
    const core = createTransportCapture({
      provider: 'claude',
      tabId: 'tab0',
      onFinalized: finalized,
      onMetric: () => {},
    });

    const reqId = core.startRequest({ url: 'https://claude.ai/api/append_message', method: 'POST' });
    core.addUserInput(reqId, 'q');

    // Navigation occurs — epoch advances
    core.setNavEpoch(1);

    // Delta arrives after nav — chunkEpoch defaults to current navEpoch=1,
    // but req.navEpoch=0 → stale_chunk_drop, delta is discarded.
    core.addAssistantDelta(reqId, 'stale delta'); // chunkEpoch=1 vs req.navEpoch=0
    core.doneRequest(reqId);

    // finalized IS called but with empty assistantText (delta was dropped)
    expect(finalized).toHaveBeenCalledOnce();
    expect(finalized.mock.calls[0][0].assistantText).toBe('');
  });

  it('abort cleans up without calling onFinalized', () => {
    const finalized = vi.fn();
    const core = createTransportCapture({
      provider: 'claude',
      tabId: 'tab0',
      onFinalized: finalized,
      onMetric: () => {},
    });

    const reqId = core.startRequest({ url: 'https://claude.ai/api/append_message', method: 'POST' });
    core.addUserInput(reqId, 'question');
    core.addAssistantDelta(reqId, 'partial');
    core.abortRequest(reqId);

    expect(finalized).not.toHaveBeenCalled();
  });

  it('finalization_timeout metric emitted on timeout', async () => {
    const metrics = [];
    const core = createTransportCapture({
      provider: 'claude',
      tabId: 'tab0',
      onFinalized: () => {},
      onMetric: (name) => metrics.push(name),
      timeoutOverrides: { first_delta_timeout_ms: 10, stream_idle_timeout_ms: 10, finalize_timeout_ms: 10 },
    });

    const reqId = core.startRequest({ url: 'https://claude.ai/api/append_message', method: 'POST' });
    core.addUserInput(reqId, 'q');
    core.addAssistantDelta(reqId, 'partial');

    // Wait for timeout to fire
    await new Promise(r => setTimeout(r, 50));

    expect(metrics).toContain('finalization_timeout_rate');
  });

  it('multiple concurrent requests isolated by requestId', () => {
    const finalized = vi.fn();
    const core = createTransportCapture({
      provider: 'chatgpt',
      tabId: 'tab0',
      onFinalized: finalized,
      onMetric: () => {},
    });

    const rA = core.startRequest({ url: 'https://chatgpt.com/backend-api/conversation', method: 'POST' });
    const rB = core.startRequest({ url: 'https://chatgpt.com/backend-api/conversation', method: 'POST' });

    core.addUserInput(rA, 'question A');
    core.addUserInput(rB, 'question B');
    core.addAssistantDelta(rA, 'answer A');
    core.addAssistantDelta(rB, 'answer B');
    core.doneRequest(rA);
    core.doneRequest(rB);

    expect(finalized).toHaveBeenCalledTimes(2);
    const texts = finalized.mock.calls.map(c => c[0].assistantText);
    expect(texts).toContain('answer A');
    expect(texts).toContain('answer B');
  });
});
