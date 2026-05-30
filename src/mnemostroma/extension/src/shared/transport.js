/** @file transport.js — POST payload to COLLECT_URL (:8766/observe) with retry logic */

import {
  COLLECT_URL,
  TRANSPORT_TIMEOUT_MS,
  TRANSPORT_RETRY_DELAYS,
} from './constants.js';

// Number of attempts = length of TRANSPORT_RETRY_DELAYS array (3)
// NOTE: no sleep between retries — setTimeout is unreliable in MV3 SW sleep cycles.
// Spec §7.6 backoff values kept in constants for future non-SW contexts.
const MAX_ATTEMPTS = TRANSPORT_RETRY_DELAYS.length;

/**
 * Отправляет exchange payload на :8766/observe.
 * 3 немедленных попытки. 4xx — выход без retry.
 * Никогда не бросает — возвращает false при полном отказе.
 * @param {Object} payload
 * @returns {Promise<boolean>}
 */
export async function postCollect(payload) {
  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    try {
      const res = await fetch(COLLECT_URL, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify(payload),
        signal:  AbortSignal.timeout(TRANSPORT_TIMEOUT_MS),
      });

      if (res.ok) return true;

      if (res.status >= 400 && res.status < 500) {
        console.error(`[Mnemostroma] transport: ${res.status} — payload rejected, no retry`);
        return false;
      }

      console.warn(`[Mnemostroma] transport: ${res.status} — attempt ${attempt + 1}/${MAX_ATTEMPTS}`);

    } catch (e) {
      console.warn(`[Mnemostroma] transport: error attempt ${attempt + 1}/${MAX_ATTEMPTS}:`, e.message);
    }
  }

  console.error('[Mnemostroma] transport: failed after all attempts');
  return false;
}
