/** @file gemini.js — Adapter for gemini.google.com */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const STOP_SELECTORS = [
  '.stop-button',
  '[aria-label="Stop"]',
  '[aria-label="Stop generating response"]',
].join(', ');

const REGENERATE_SELECTORS = [
  '[aria-label="Regenerate draft"]',
  '[aria-label="Regenerate"]',
  '[aria-label="Retry"]',
].join(', ');

/**
 * Извлекает chat_id из всех доступных источников.
 * Уровень 1: data-атрибуты в DOM
 * Уровень 2: window.__mnemo_gemini_chat_id (fetch interceptor из index.js)
 * Уровень 3: sessionStorage
 * Уровень 4: crypto.randomUUID() → sessionStorage
 *
 * ВАЖНО: уровень 2 при старте всегда пуст — interceptor ещё не сработал.
 * index.js должен переинициализировать сессию когда interceptor найдёт реальный ID.
 *
 * Всегда возвращает string (UUID если реальный ID недоступен).
 * Никогда не возвращает null в отличие от других адаптеров.
 * @param {string} _url
 * @returns {string}
 */
export function extractChatId(_url) {
  // Уровень 1: data-атрибуты в DOM
  const domEl = document.querySelector(
    '[data-thread-id], [data-conversation-id]'
  );
  if (domEl) {
    const id = domEl.dataset.threadId ?? domEl.dataset.conversationId;
    if (id) return id;
  }

  // Уровень 2: fetch interceptor
  if (typeof window.__mnemo_gemini_chat_id === 'string'
      && window.__mnemo_gemini_chat_id.length > 0) {
    return window.__mnemo_gemini_chat_id;
  }

  // Уровень 3: sessionStorage
  try {
    const stored = sessionStorage.getItem('mnemo_gemini_chat_id');
    if (stored) return stored;
  } catch {}

  // Уровень 4: UUID fallback
  const id = crypto.randomUUID();
  try {
    sessionStorage.setItem('mnemo_gemini_chat_id', id);
  } catch {}
  return id;
}

/**
 * No-op — Gemini сохраняет промпт в DOM после отправки,
 * перехват до отправки не нужен.
 */
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
      const loadEl = document.querySelector(
        'model-response .loading-indicator, .response-container .loading-indicator'
      ) ?? document.querySelector('.loading-indicator');

      const isStreaming = !!(stopEl || loadEl);

      if (isStreaming) {
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
export function extractUserMessage(selector = '.user-query') {
  try {
    const messages = document.querySelectorAll(selector);
    if (messages.length === 0) return '';
    return messages[messages.length - 1].textContent.trim();
  } catch {
    return '';
  }
}

/**
 * Берёт последний непустой драфт.
 * Gemini показывает несколько драфтов при Regenerate.
 * @param {string} selector
 * @returns {string}
 */
export function extractLlmResponse(selector) {
  try {
    const all = document.querySelectorAll(selector);
    if (all.length === 0) return '';
    for (let i = all.length - 1; i >= 0; i--) {
      if (all[i].childNodes.length === 0) continue;
      const text = all[i].textContent.trim();
      if (text.length > 0) return text;
    }
    return '';
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
