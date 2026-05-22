/** @file chatgpt.js — Adapter for chatgpt.com */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const STOP_SELECTORS = [
  '[aria-label="Stop streaming"]',
  '[aria-label="Stop generating"]',
  '[aria-label="Stop"]',
].join(', ');

const REGENERATE_SELECTORS = [
  '[aria-label="Regenerate"]',
  '[aria-label="Regenerate response"]',
].join(', ');

export function extractChatId(url) {
  try {
    const { pathname } = new URL(url);
    // Работает для /c/{id} и /g/{gptId}/c/{id} (GPTs)
    const match = pathname.match(/\/c\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

export function initSubmitListener(_cb) {}

/**
 * Дебаунс 50мс снижает нагрузку от тысяч мутаций при стриминге.
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
      const stopBtn = document.querySelector(STOP_SELECTORS);

      if (stopBtn) {
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
 * @param {string} [selector]
 * @returns {string}
 */
export function extractUserMessage(selector = '[data-message-author-role="user"]') {
  try {
    const messages = document.querySelectorAll(selector);
    if (messages.length === 0) return '';
    const last = messages[messages.length - 1];
    const textEl = last.querySelector('.whitespace-pre-wrap')
                ?? last.querySelector('[data-message-text-content]')
                ?? last;
    return textEl.textContent.trim();
  } catch {
    return '';
  }
}

export function extractLlmResponse(selector) {
  try {
    const all = document.querySelectorAll(selector);
    if (all.length === 0) return '';
    return all[all.length - 1].textContent.trim();
  } catch {
    return '';
  }
}

export function onRegenerate(cb) {
  const handler = (e) => {
    if (e.target.closest(REGENERATE_SELECTORS)) cb();
  };
  document.addEventListener('click', handler);
  return () => document.removeEventListener('click', handler);
}
