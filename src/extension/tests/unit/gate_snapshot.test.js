import { describe, it, expect } from 'vitest';
import { buildGateSnapshot } from '../../src/shared/gate_snapshot.js';

describe('gate snapshot', () => {
  it('builds snapshot and fails sample gate on empty data', () => {
    const snap = buildGateSnapshot('claude', {
      transport_success: 0,
      dom_fallback: 0,
      parse_error: 0,
      duplicate_drop: 0,
      finalization_timeout: 0,
      total_finalized: 0,
    });
    expect(snap.provider).toBe('claude');
    expect(snap.gate_a.pass).toBe(false);
    expect(snap.gate_b.pass).toBe(false);
  });

  it('passes Gate A with valid sample and rates', () => {
    const m = {
      transport_success: 480,
      dom_fallback: 20,
      parse_error: 5,
      duplicate_drop: 0,
      finalization_timeout: 0,
      total_finalized: 500,
    };
    const snap = buildGateSnapshot('chatgpt', m);
    expect(snap.gate_a.pass).toBe(true);
  });
});
