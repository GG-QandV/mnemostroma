import { describe, it, expect, vi } from 'vitest';
import {
  DEFAULT_CAPTURE_MODE,
  CAPTURE_MODE_DOM_ONLY,
  CAPTURE_MODE_TRANSPORT_FIRST,
  CAPTURE_SOURCE_DOM
} from '../../src/shared/constants.js';
import { calculateRates, METRIC_KEYS, createEmptyMetrics } from '../../src/shared/metrics.js';
import { checkGate } from '../../src/shared/gates.js';

// Mock api for metrics.js
vi.mock('../../src/shared/compat.js', () => ({
  default: {
    storage: {
      local: {
        get: vi.fn(),
        set: vi.fn()
      }
    }
  }
}));

describe('Phase 0 Baseline', () => {
  it('CAPTURE_MODE default is transport_first (Phase 3 migration)', () => {
    expect(DEFAULT_CAPTURE_MODE).toBe(CAPTURE_MODE_TRANSPORT_FIRST);
  });

  it('CAPTURE_SOURCE_DOM should be dom_fallback', () => {
    expect(CAPTURE_SOURCE_DOM).toBe('dom_fallback');
  });
});

describe('Metrics calculateRates', () => {
  it('returns zero/neutral values for empty metrics', () => {
    const empty = createEmptyMetrics();
    const rates = calculateRates(empty);
    expect(rates.transport_success_rate).toBe(0);
    expect(rates.dom_fallback_rate).toBe(0);
    expect(rates.parse_error_rate).toBe(0);
    expect(rates.sample_size).toBe(0);
  });

  it('calculates rates correctly for mixed data', () => {
    const metrics = {
      [METRIC_KEYS.TRANSPORT_SUCCESS]: 95,
      [METRIC_KEYS.DOM_FALLBACK]: 5,
      [METRIC_KEYS.TOTAL]: 100,
      [METRIC_KEYS.PARSE_ERROR]: 2,
      [METRIC_KEYS.DUPLICATE_DROP]: 1,
      [METRIC_KEYS.TIMEOUT]: 0
    };
    const rates = calculateRates(metrics);
    expect(rates.transport_success_rate).toBe(95);
    expect(rates.dom_fallback_rate).toBe(5);
    expect(rates.parse_error_rate).toBe(2);
    expect(rates.duplicate_drop_rate).toBe(1);
    expect(rates.sample_size).toBe(100);
  });
});

describe('Gate Check Helper', () => {
  it('fails Gate A if sample size is insufficient', () => {
    const metrics = { ...createEmptyMetrics(), [METRIC_KEYS.TOTAL]: 100 };
    const res = checkGate(metrics, 'GATE_A');
    expect(res.pass).toBe(false);
    expect(res.reason).toContain('Insufficient sample size');
  });

  it('passes Gate A with 96% success and 1% error', () => {
    const metrics = {
      [METRIC_KEYS.TRANSPORT_SUCCESS]: 480,
      [METRIC_KEYS.DOM_FALLBACK]: 20,
      [METRIC_KEYS.TOTAL]: 500,
      [METRIC_KEYS.PARSE_ERROR]: 5, // 1%
      [METRIC_KEYS.DUPLICATE_DROP]: 0,
      [METRIC_KEYS.TIMEOUT]: 0
    };
    const res = checkGate(metrics, 'GATE_A');
    expect(res.pass).toBe(true);
  });

  it('fails Gate A with 94% success', () => {
    const metrics = {
      [METRIC_KEYS.TRANSPORT_SUCCESS]: 470,
      [METRIC_KEYS.DOM_FALLBACK]: 30,
      [METRIC_KEYS.TOTAL]: 500,
      [METRIC_KEYS.PARSE_ERROR]: 0,
      [METRIC_KEYS.DUPLICATE_DROP]: 0,
      [METRIC_KEYS.TIMEOUT]: 0
    };
    const res = checkGate(metrics, 'GATE_A');
    expect(res.pass).toBe(false);
    expect(res.reason).toContain('Transport success rate too low');
  });

  it('passes Gate B with high stability and 2000 samples', () => {
    const metrics = {
      [METRIC_KEYS.TRANSPORT_SUCCESS]: 1990,
      [METRIC_KEYS.DOM_FALLBACK]: 10,
      [METRIC_KEYS.TOTAL]: 2000,
      [METRIC_KEYS.PARSE_ERROR]: 0,
      [METRIC_KEYS.DUPLICATE_DROP]: 10, // 0.5%
      [METRIC_KEYS.TIMEOUT]: 5 // 0.25%
    };
    const res = checkGate(metrics, 'GATE_B');
    expect(res.pass).toBe(true);
  });

  it('fails Gate B if duplicate drop is too high', () => {
    const metrics = {
      [METRIC_KEYS.TRANSPORT_SUCCESS]: 1980,
      [METRIC_KEYS.DOM_FALLBACK]: 20,
      [METRIC_KEYS.TOTAL]: 2000,
      [METRIC_KEYS.PARSE_ERROR]: 0,
      [METRIC_KEYS.DUPLICATE_DROP]: 30, // 1.5% (> 1%)
      [METRIC_KEYS.TIMEOUT]: 0
    };
    const res = checkGate(metrics, 'GATE_B');
    expect(res.pass).toBe(false);
    expect(res.reason).toContain('Duplicate drop rate too high');
  });
});
