/** @file deepseek.js — Adapter for deepseek.com */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const STOP_SELECTORS = [
  '.stop-button:not([disabled])',
  '[aria-label="Stop"]',
  '[aria-label="Stop generating"]',
].join(', ');

const REGENERATE_SELECTORS = [
  '[aria-label="Regenerate"]',
  '[aria-label="Retry"]',
].join(', ');

function _isVisible(el) {
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

/**
 * Извлекает chat_id из URL.
 * /chat/new → null (несохранённый чат, коллизия session_id иначе).
 * @param {string} url
 * @returns {string|null}
 */
export function extractChatId(url) {
  try {
    const { pathname } = new URL(url);
    const match = pathname.match(/\/chat\/([a-zA-Z0-9_-]+)/);
    if (!match) return null;
    if (match[1] === 'new') return null;
    return match[1];
  } catch {
    return null;
  }
}

/** No-op — только grok.js перехватывает submit. */
export function initSubmitListener(_cb) {}

/**
 * @param {string} _selector
 * @param {() => void} cb
 */
export function getStreamEndSignal(_selector, cb) {
  let wasStreaming = false;
  let checkTimer  = null;

  const observer = new MutationObserver(() => {
    if (checkTimer) return;
    checkTimer = setTimeout(() => {
      checkTimer = null;
      const stopEl = document.querySelector(STOP_SELECTORS);

      if (stopEl && _isVisible(stopEl)) {
        wasStreaming = true;
        return;
      }

      if (wasStreaming) {
        wasStreaming = false;
        setTimeout(cb, STREAM_END_SETTLE_MS);
      }
    }, 50);
  });

  observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Многоуровневый fallback — .fbb737a4 меняется при каждом билде DeepSeek.
 * @param {string} [selector]
 * @returns {string}
 */
export function extractUserMessage(selector = '.fbb737a4') {
  try {
    let messages = document.querySelectorAll(selector);

    if (messages.length === 0) {
      messages = document.querySelectorAll(
        '[data-role="user"], [data-message-role="user"]'
      );
    }

    if (messages.length === 0) {
      const responses = document.querySelectorAll('.ds-markdown');
      if (responses.length > 0) {
        const prev = responses[responses.length - 1]
          .closest('[class]')?.previousElementSibling;
        if (prev) return prev.textContent.trim();
      }
    }

    if (messages.length === 0) return '';
    return messages[messages.length - 1].textContent.trim();
  } catch {
    return '';
  }
}

/**
 * Удаляет thinking блоки DeepSeek R1 перед извлечением текста.
 * @param {string} selector
 * @returns {string}
 */
export function extractLlmResponse(selector) {
  try {
    const all = document.querySelectorAll(selector);
    if (all.length === 0) return '';
    const clone = all[all.length - 1].cloneNode(true);
    clone.querySelectorAll(
      '[class*="think"], [class*="reasoning"], details'
    ).forEach(el => el.remove());
    return clone.textContent.trim();
  } catch {
    return '';
  }
}

/**
 * @param {() => void} cb
 * @returns {() => void} unsubscribe
 */
export function onRegenerate(cb) {
  const handler = (e) => {
    if (e.target.closest(REGENERATE_SELECTORS)) cb();
  };
  document.addEventListener('click', handler);
  return () => document.removeEventListener('click', handler);
}
