/** @file grok.js — Adapter for grok.com */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const STOP_SELECTORS = [
  '[aria-label="Stop"]',
  '[aria-label="Stop generating"]',
  '.stop-button',
].join(', ');

const REGENERATE_SELECTORS = [
  '[aria-label="Regenerate"]',
  '[aria-label="Retry"]',
].join(', ');

/**
 * Извлекает chat_id из URL.
 * @param {string} url
 * @returns {string|null}
 */
export function extractChatId(url) {
  try {
    const { pathname } = new URL(url);
    const match = pathname.match(/\/chat\/([a-zA-Z0-9_-]+)/);
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

/**
 * Инициализирует слушатель отправки сообщения для Grok.
 * @param {() => void} cb
 * @returns {() => void} unsubscribe
 */
export function initSubmitListener(cb) {
  const handler = (e) => {
    if (e.type === 'click') {
      const btn = e.target.closest('button[type="submit"], [aria-label="Send message"], button[aria-label="Grok message"]');
      if (btn) cb();
    } else if (e.type === 'keydown') {
      if (e.key === 'Enter' && !e.shiftKey) {
        const textarea = e.target.closest('textarea, [contenteditable="true"]');
        if (textarea) cb();
      }
    }
  };

  document.addEventListener('click', handler, { capture: true });
  document.addEventListener('keydown', handler, { capture: true });

  return () => {
    document.removeEventListener('click', handler, { capture: true });
    document.removeEventListener('keydown', handler, { capture: true });
  };
}

/**
 * Наблюдение за концом стриминга для Grok.
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

  observer.observe(document.body, { childList: true, subtree: true });
}

/**
 * Извлекает последнее сообщение пользователя.
 * @param {string} [selector]
 * @returns {string}
 */
export function extractUserMessage(selector = '[data-testid="message-user"], .user-message') {
  try {
    const messages = document.querySelectorAll(selector);
    if (messages.length === 0) {
      // Fallback selector
      const allMsgs = document.querySelectorAll('[data-testid="message"]');
      const userMsgs = [...allMsgs].filter(el => el.getAttribute('data-testid')?.includes('user') || el.innerText?.startsWith('You:'));
      if (userMsgs.length > 0) {
        return userMsgs[userMsgs.length - 1].textContent.trim();
      }
      return '';
    }
    return messages[messages.length - 1].textContent.trim();
  } catch {
    return '';
  }
}

/**
 * Извлекает последний ответ LLM.
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
 * Регистрация коллбека регенерации ответа.
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
