/** @file session.js — Session and exchange ID generation logic */

import { HOSTNAME_SHORT } from './constants.js';

export function shortHostname(hostname) {
  return HOSTNAME_SHORT[hostname] || hostname;
}

export function generateSessionId(hostname, chatId) {
  const shortName  = shortHostname(hostname);
  const unixSeconds = Math.floor(Date.now() / 1000);
  return `browser-${shortName}-${chatId}-${unixSeconds}`;
}

export function generateExchangeId(sessionId, counter) {
  return `${sessionId}-${counter}`;
}

export function generateRegenerateId(sessionId, counter, n) {
  return `${sessionId}-${counter}-r${n}`;
}

/**
 * Извлекает chat_id из URL по hostname.
 * Gemini и grok.com (v1.1) — возвращают null, обрабатываются в адаптере.
 * @param {string} url
 * @param {string} hostname
 * @returns {string|null}
 */
export function extractChatIdFromUrl(url, hostname) {
  try {
    const pathname = new URL(url).pathname;

    const patterns = {
      'claude.ai':     /\/chat\/([a-zA-Z0-9_-]+)/,
      'chatgpt.com':   /\/c\/([a-zA-Z0-9_-]+)/,
      'perplexity.ai': /\/search\/([a-zA-Z0-9_-]+)/,
      'deepseek.com':  /\/chat\/(?:s\/)?([a-zA-Z0-9_-]+)/,
      'chat.deepseek.com': /\/chat\/(?:s\/)?([a-zA-Z0-9_-]+)/,
    };

    const regex = patterns[hostname];
    if (!regex) return null;

    const match = pathname.match(regex);
    return match ? match[1] : null;

  } catch (err) {
    console.warn('[Mnemostroma] extractChatIdFromUrl failed:', err.message);
    return null;
  }
}
