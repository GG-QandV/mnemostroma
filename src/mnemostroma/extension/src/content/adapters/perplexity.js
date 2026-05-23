/** @file perplexity.js — Adapter for perplexity.ai */

import { STREAM_END_SETTLE_MS } from '../../shared/constants.js';

const STOP_SELECTORS = [
  '[data-status="streaming"]',
  '[aria-label*="Stop"]',
  '[aria-label*="Зупинити"]',
  '[aria-label*="Остановить"]',
  '[aria-label*="Detener"]',
  '[aria-label*="Stop generating"]',
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

/**
 * Устанавливает слушатель отправки запроса.
 * Отслеживает нажатие Enter (без Shift) внутри [contenteditable="true"]
 * и клики по кнопке отправки.
 * @param {() => void} cb
 */
export function initSubmitListener(cb) {
  let isSubmitting = false;

  const handleSubmit = () => {
    console.debug('[Mnemostroma-Perplexity-Debug] initSubmitListener: handleSubmit triggered, isSubmitting =', isSubmitting);
    if (isSubmitting) return;
    isSubmitting = true;
    cb();
    setTimeout(() => { isSubmitting = false; }, 1000);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      const activeEl = document.activeElement;
      console.debug('[Mnemostroma-Perplexity-Debug] initSubmitListener: KeyDown Enter, activeElement =', activeEl);
      if (activeEl && activeEl.matches('[contenteditable="true"]')) {
        console.debug('[Mnemostroma-Perplexity-Debug] initSubmitListener: Matches [contenteditable="true"], text =', activeEl.textContent);
        // Даем браузеру обработать событие, затем вызываем cb
        setTimeout(handleSubmit, 0);
      }
    }
  };

  const handleClick = (e) => {
    const button = e.target.closest('button[aria-label*="Отправить"], button[aria-label*="Надіслати"], button[aria-label*="Send"], button.bg-button-bg');
    if (button) {
      console.debug('[Mnemostroma-Perplexity-Debug] initSubmitListener: Click on submit button =', button);
      handleSubmit();
    }
  };

  document.addEventListener('keydown', handleKeyDown, true);
  document.addEventListener('click', handleClick, true);

  return () => {
    document.removeEventListener('keydown', handleKeyDown, true);
    document.removeEventListener('click', handleClick, true);
  };
}

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
 * Извлекает последнее сообщение пользователя.
 * Сначала пробует прочитать активное поле ввода div[contenteditable="true"],
 * а если оно уже очищено — использует fallback на последний [class*="group/query"].
 * @param {string} [selector]
 * @returns {string}
 */
export function extractUserMessage(selector = '[contenteditable="true"]') {
  console.debug('[Mnemostroma-Perplexity-Debug] extractUserMessage called with selector =', selector);
  try {
    const activeInput = document.querySelector(selector);
    console.debug('[Mnemostroma-Perplexity-Debug] extractUserMessage: activeInput =', activeInput);
    if (activeInput) {
      const text = activeInput.textContent.trim();
      console.debug('[Mnemostroma-Perplexity-Debug] extractUserMessage: activeInput text =', text);
      if (text) return text;
    }

    const sentMessages = document.querySelectorAll('[class*="group/query"]');
    console.debug('[Mnemostroma-Perplexity-Debug] extractUserMessage: sentMessages found count =', sentMessages.length);
    if (sentMessages.length > 0) {
      const lastText = sentMessages[sentMessages.length - 1].textContent.trim();
      console.debug('[Mnemostroma-Perplexity-Debug] extractUserMessage: sentMessages lastText =', lastText);
      return lastText;
    }

    console.debug('[Mnemostroma-Perplexity-Debug] extractUserMessage: returning empty string');
    return '';
  } catch (err) {
    console.error('[Mnemostroma-Perplexity-Debug] extractUserMessage error:', err);
    return '';
  }
}

/**
 * @param {string} selector
 * @returns {string}
 */
export function extractLlmResponse(selector) {
  console.debug('[Mnemostroma-Perplexity-Debug] extractLlmResponse called with selector =', selector);
  try {
    const all = document.querySelectorAll(selector);
    console.debug('[Mnemostroma-Perplexity-Debug] extractLlmResponse: elements found count =', all.length);
    if (all.length === 0) return '';
    const lastText = all[all.length - 1].textContent.trim();
    console.debug('[Mnemostroma-Perplexity-Debug] extractLlmResponse: lastText =', lastText);
    return lastText;
  } catch (err) {
    console.error('[Mnemostroma-Perplexity-Debug] extractLlmResponse error:', err);
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
