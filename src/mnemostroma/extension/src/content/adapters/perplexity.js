/** @file perplexity.js — Adapter for perplexity.ai */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const STOP_SELECTORS = [
  '[data-status="streaming"]',
  '[aria-label="Stop"]',
  '[aria-label="Stop generating"]',
].join(', ');

const REGENERATE_SELECTORS = [
  '[aria-label="Rewrite"]',
  '[aria-label="Regenerate"]',
].join(', ');

/**
 * Извлекает chat_id из URL.
 * Поддерживает: /search/{id}, /p/{slug}, /s/{shortId}
 * @param {string} url
 * @returns {string|null}
 */
export function extractChatId(url) {
  try {
    const { pathname } = new URL(url);
    const match = pathname.match(/\/(?:search|p|s)\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

/** No-op — только grok.js перехватывает submit. */
export function initSubmitListener(_cb) {}

/**
 * Устанавливает постоянное наблюдение за концом стриминга.
 * Ловит как исчезновение элементов (childList) так и
 * изменение data-status атрибута (attributes).
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

      if (stopEl) {
        wasStreaming = true;
        return;
      }

      if (wasStreaming) {
        wasStreaming = false;
        setTimeout(cb, STREAM_END_SETTLE_MS);
      }
    }, 50);
  });

  observer.observe(document.body, {
    childList:       true,
    subtree:         true,
    attributes:      true,
    attributeFilter: ['data-status'],
  });
}

/**
 * @param {string} [selector]
 * @returns {string}
 */
export function extractUserMessage(selector = '.my-query') {
  try {
    const messages = document.querySelectorAll(selector);
    if (messages.length === 0) return '';
    return messages[messages.length - 1].textContent.trim();
  } catch {
    return '';
  }
}

/**
 * @param {string} selector
 * @returns {string}
 */
export function extractLlmResponse(selector) {
  try {
    const all = document.querySelectorAll(selector);
    if (all.length === 0) return '';
    return all[all.length - 1].textContent.trim();
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
