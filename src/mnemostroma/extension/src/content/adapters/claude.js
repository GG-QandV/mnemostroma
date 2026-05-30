/** @file claude.js — Adapter for claude.ai */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const REGENERATE_SELECTORS = [
  '[aria-label="Retry"]',
  '[aria-label="Retry message"]',
  '[aria-label="Regenerate response"]',
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

/** No-op — только grok.js перехватывает submit. */
export function initSubmitListener(_cb) {}

/**
 * Устанавливает постоянное наблюдение за концом стриминга.
 * Конец = переход: stopButton есть → stopButton исчез.
 * Observer живёт всё время страницы — работает для всех exchanges в SPA.
 * @param {string} _selector — не используется (stopButton вне responseContainer)
 * @param {() => void} cb
 */
export function getStreamEndSignal(selector, cb) {
  let timer = null;
  let lastText = '';
  let isStreaming = false;

  const observer = new MutationObserver(() => {
    const responses = document.querySelectorAll(selector || '.font-claude-response');
    if (responses.length === 0) return;

    const latestResponse = responses[responses.length - 1];
    const currentText = latestResponse.textContent;

    if (currentText !== lastText) {
      lastText = currentText;
      isStreaming = true;
      clearTimeout(timer);
      timer = setTimeout(() => {
        if (isStreaming) {
          isStreaming = false;
          cb();
        }
      }, STREAM_END_SETTLE_MS);
    }
  });

  observer.observe(document.body, { childList: true, subtree: true, characterData: true });
}

/**
 * Возвращает текст последнего промпта пользователя.
 * @param {string} [selector]
 * @returns {string}
 */
export function extractUserMessage(selector = '[data-testid="user-message"]') {
  try {
    const messages = document.querySelectorAll(selector);
    if (messages.length === 0) return '';
    return messages[messages.length - 1].textContent.trim();
  } catch {
    return '';
  }
}

/**
 * Возвращает текст последнего ответа LLM.
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
 * Регистрирует слушатель кнопки Regenerate.
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
