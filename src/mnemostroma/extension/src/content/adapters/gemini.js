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
  const domEl = document.querySelector('[data-thread-id], [data-conversation-id]');
  if (domEl) {
    const id = domEl.dataset.threadId ?? domEl.dataset.conversationId;
    if (id) return id;
  }
  if (typeof window.__mnemo_gemini_chat_id === 'string' && window.__mnemo_gemini_chat_id.length > 0) return window.__mnemo_gemini_chat_id;
  try { const stored = sessionStorage.getItem('mnemo_gemini_chat_id'); if (stored) return stored; } catch {}
  const id = crypto.randomUUID();
  try { sessionStorage.setItem('mnemo_gemini_chat_id', id); } catch {}
  return id;
}

export function initSubmitListener(cb) {
  let wasGenerating = false;
  setInterval(() => {
    const spinners = document.querySelectorAll('.loading-content-spinner-container, .mat-mdc-progress-spinner');
    let isGenerating = false;
    for (const s of spinners) {
      if (s.getBoundingClientRect().width > 0 && window.getComputedStyle(s).visibility !== 'hidden') {
        isGenerating = true;
        break;
      }
    }
    
    if (isGenerating && !wasGenerating) {
      wasGenerating = true;
    } else if (!isGenerating && wasGenerating) {
      wasGenerating = false;
      const allRes = document.querySelectorAll('message-content, .model-response-text');
      const responseEl = allRes.length ? allRes[allRes.length - 1] : null;
      if (responseEl) cb(responseEl);
    }
  }, 500);
}

export function extractUserMessage(selector = '.user-query') {
  try {
    const messages = document.querySelectorAll(selector);
    if (messages.length === 0) return '';
    return messages[messages.length - 1].textContent.trim();
  } catch { return ''; }
}

export function extractLlmResponse(responseEl) {
  // `responseEl` is DOM element passed from `index.js` or string selector
  if (typeof responseEl === 'string') {
    try {
      const all = document.querySelectorAll(responseEl);
      if (all.length === 0) return '';
      for (let i = all.length - 1; i >= 0; i--) {
        if (all[i].childNodes.length === 0) continue;
        const text = all[i].textContent.trim();
        if (text.length > 0) return text;
      }
      return '';
    } catch { return ''; }
  }
  return responseEl?.innerText || '';
}

export function onRegenerate(cb) {
  const handler = (e) => {
    if (e.target.closest('[aria-label="Regenerate draft"], [aria-label="Regenerate"], [aria-label="Retry"], [aria-label="Повторить"]')) cb();
  };
  document.addEventListener('click', handler);
  return () => document.removeEventListener('click', handler);
}
