/** @file selectors.js — CSS selector loading: cache → GitHub → hardcoded fallback */

import api from './compat.js';
import { SELECTORS_REMOTE_URL, SELECTORS_CACHE_TTL_MS } from './constants.js';

/** @typedef {Object} SelectorConfig
 * @property {string} responseContainer
 * @property {string} stopButton
 * @property {string} userMessage
 * @property {string} regenerateButton
 */

const HARDCODED_SELECTORS = {
  'claude.ai': {
    responseContainer: '.font-claude-response',
    stopButton:        '[aria-label="Stop Response"]',
    userMessage:       '.\\!font-user-message',
    regenerateButton:  '[aria-label="Retry"]',
  },
  'chatgpt.com': {
    responseContainer: '[data-message-author-role="assistant"]',
    stopButton:        '[aria-label="Stop streaming"], [data-testid="stop-button"]',
    userMessage:       '[data-message-author-role="user"]',
    regenerateButton:  '[aria-label="Regenerate"]',
  },
  'chat.openai.com': {
    responseContainer: '[data-message-author-role="assistant"]',
    stopButton:        '[aria-label="Stop streaming"], [data-testid="stop-button"]',
    userMessage:       '[data-message-author-role="user"]',
    regenerateButton:  '[aria-label="Regenerate"]',
  },
  'perplexity.ai': {
    responseContainer: '.prose',
    stopButton:        '[data-status="streaming"], [aria-label*="Stop"], [aria-label*="Зупинити"], [aria-label*="Остановить"], [aria-label*="Detener"], [aria-label*="Stop generating"]',
    userMessage:       '[contenteditable="true"]',
    regenerateButton:  '[aria-label="Rewrite"]',
  },
  'www.perplexity.ai': {
    responseContainer: '.prose',
    stopButton:        '[data-status="streaming"], [aria-label*="Stop"], [aria-label*="Зупинити"], [aria-label*="Остановить"], [aria-label*="Detener"], [aria-label*="Stop generating"]',
    userMessage:       '[contenteditable="true"]',
    regenerateButton:  '[aria-label="Rewrite"]',
  },
  'gemini.google.com': {
    responseContainer: 'message-content, .model-response-text',
    stopButton:        '.loading-content-spinner-container, .mat-mdc-progress-spinner, button[aria-label*="Stop generating"], button[aria-label*="Stop response"], button[aria-label*="Зупинити генерацію"], button[aria-label*="Остановить генерацию"], .stop-button',
    userMessage:       '.query-text, .user-query',
    regenerateButton:  '[aria-label="Regenerate draft"], [aria-label="Повторить"]',
  },
  'deepseek.com': {
    responseContainer: '.ds-markdown',
    stopButton:        '.stop-button',
    userMessage:       '.fbb737a4',
    regenerateButton:  '[aria-label="Regenerate"]',
  },
  'chat.deepseek.com': {
    responseContainer: '.ds-markdown',
    stopButton:        '.stop-button',
    userMessage:       '.fbb737a4',
    regenerateButton:  '[aria-label="Regenerate"]',
  },
  'grok.com': {
    responseContainer: '.message-bubble',
    stopButton:        '[aria-label="Stop streaming"]',
    userMessage:       '.user-message',
    regenerateButton:  '[aria-label="Regenerate"]',
  },
  'x.com': {
    responseContainer: '.message-bubble',
    stopButton:        '[aria-label="Stop streaming"]',
    userMessage:       '.user-message',
    regenerateButton:  '[aria-label="Regenerate"]',
  },
};

async function _loadFromCache(hostname) {
  try {
    const raw = sessionStorage.getItem('mnemo_selectors_cache');
    if (!raw) return null;
    const { data, timestamp } = JSON.parse(raw);
    if (Date.now() - timestamp > SELECTORS_CACHE_TTL_MS) return null;
    return data[hostname] ?? null;
  } catch { return null; }
}

async function _fetchRemote() {
  return new Promise((resolve, reject) => {
    const id = Math.random().toString(36).substring(2);
    const timeout = setTimeout(() => {
      window.removeEventListener('message', handler);
      reject(new Error('timeout'));
    }, 5000);

    const handler = (event) => {
      if (event.source !== window || event.origin !== window.location.origin) return;
      const msg = event.data;
      if (msg && msg.__mnemo_reply && msg.id === id) {
        window.removeEventListener('message', handler);
        clearTimeout(timeout);
        if (msg.res && msg.res.ok) resolve(msg.res.data);
        else reject(new Error('Remote fetch via SW failed'));
      }
    };

    window.addEventListener('message', handler);
    window.postMessage({ __mnemo: true, type: 'FETCH_SELECTORS', id }, window.location.origin);
  });
}

async function _saveToCache(data) {
  try {
    sessionStorage.setItem('mnemo_selectors_cache', JSON.stringify({
      data, timestamp: Date.now()
    }));
  } catch { }
}

/**
 * Возвращает SelectorConfig для hostname.
 * Порядок: cache → GitHub JSON → hardcoded fallback.
 * v1.0: устаревший кеш не используется как fallback — known limitation.
 * @param {string} hostname
 * @returns {Promise<SelectorConfig|null>}
 */
export async function getSelectors(hostname) {
  const cached = await _loadFromCache(hostname);
  if (cached) return cached;

  try {
    const data = await _fetchRemote();
    await _saveToCache(data);
    if (data[hostname]) return data[hostname];
    console.warn(`[Mnemostroma] selectors: ${hostname} not in remote, using hardcoded`);
  } catch (err) {
    console.debug(`[Mnemostroma] selectors: remote fetch failed: ${err.message} (normal if selectors.json not deployed yet)`);
  }

  const fallback = HARDCODED_SELECTORS[hostname];
  if (!fallback) {
    console.warn(`[Mnemostroma] selectors: no config for: ${hostname}`);
    return null;
  }
  return fallback;
}

/**
 * Проверяет, находит ли CSS-селектор хотя бы один элемент в DOM.
 * Используется в index.js перед запуском discovery.
 * @param {string} hostname — для логирования
 * @param {string|undefined} selector
 * @returns {Promise<boolean>}
 */
export async function checkSelector(hostname, selector) {
  if (!selector) return false;
  try {
    const found = document.querySelector(selector) !== null;
    if (!found) {
      console.debug(`[Mnemostroma] checkSelector: not found "${selector}" on ${hostname} (normal on empty SPA load)`);
    }
    return found;
  } catch (err) {
    // Невалидный CSS-селектор
    console.warn(`[Mnemostroma] checkSelector: invalid selector "${selector}":`, err.message);
    return false;
  }
}
