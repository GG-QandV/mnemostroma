import { describe, it, expect } from 'vitest';
import {
  CAPTURE_MODE_DOM_ONLY,
  CAPTURE_MODE_TRANSPORT_FIRST,
  CAPTURE_MODE_TRANSPORT_ONLY,
} from '../../src/shared/constants.js';
import { shouldEnableDomObserver } from '../../src/shared/capture_mode.js';

describe('capture mode dom fallback policy', () => {
  it('keeps DOM observer enabled in dom_only', () => {
    expect(shouldEnableDomObserver(CAPTURE_MODE_DOM_ONLY)).toBe(true);
  });

  it('keeps DOM observer enabled in transport_first (fallback)', () => {
    expect(shouldEnableDomObserver(CAPTURE_MODE_TRANSPORT_FIRST)).toBe(true);
  });

  it('disables DOM observer only in transport_only', () => {
    expect(shouldEnableDomObserver(CAPTURE_MODE_TRANSPORT_ONLY)).toBe(false);
  });
});
