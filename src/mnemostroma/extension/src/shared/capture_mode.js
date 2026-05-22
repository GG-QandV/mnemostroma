import { CAPTURE_MODE_TRANSPORT_ONLY } from './constants.js';

export function shouldEnableDomObserver(mode) {
  return mode !== CAPTURE_MODE_TRANSPORT_ONLY;
}

