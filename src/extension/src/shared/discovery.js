/** @file discovery.js — Auto-discovery of broken CSS selectors via DOM heuristics */

import api from './compat.js';
import { DISCOVERY_CONFIDENCE_MIN } from './constants.js';

const MAX_POSSIBLE_SCORE = 8;

function _escapeClass(cls) {
  if (typeof CSS !== 'undefined' && CSS.escape) return CSS.escape(cls);
  return cls.replace(/[^\w-]/g, '\\$&');
}

export async function checkSelector(hostname, selector) {
  try {
    if (!selector) return false;
    const elements = document.querySelectorAll(selector);
    for (const el of elements) {
      if (el.textContent.trim().length > 0) return true;
    }
    return false;
  } catch (err) {
    console.warn('[Mnemostroma] discovery: checkSelector failed:', err.message);
    return false;
  }
}

async function _loadSelectorsDb(hostname) {
  try {
    const key = `selectors_db_${hostname}`;
    const raw = sessionStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw) ?? null;
  } catch { return null; }
}

function _scoreCandidate(el, userMessageEl) {
  let score = 0;
  if (el.textContent.trim().length > 200) score += 3;
  if (el.querySelector('code, table, ul, p')) score += 2;
  if (userMessageEl) {
    const position = userMessageEl.compareDocumentPosition(el);
    if (position & Node.DOCUMENT_POSITION_FOLLOWING) score += 2;
    const userRect = userMessageEl.getBoundingClientRect();
    const elRect   = el.getBoundingClientRect();
    if (elRect.top > userRect.top) score += 1;
  }
  return score;
}

/**
 * Пытается найти новый рабочий селектор через эвристику.
 * Вызывать ПОСЛЕ первого промпта — до этого userMessage отсутствует
 * и confidence будет ниже порога (max 3/8 = 0.375).
 * @param {string} hostname
 * @returns {Promise<string|null>}
 */
export async function discoverSelector(hostname) {
  try {
    const db = await _loadSelectorsDb(hostname);
    const knownSelectors = new Set([
      ...(db?.previous ?? []),
      ...(db?.current  ?? []),
      ...(db?.working  ? [db.working] : []),
    ]);

    const userMessageEl = (() => {
      const all = document.querySelectorAll(
        '[class*="user"], [data-message-author-role="user"], .my-query, .user-query'
      );
      return all.length > 0 ? all[all.length - 1] : null;
    })();

    const candidates = document.querySelectorAll('div, article, section, main');
    const seen   = new Set();
    const scored = [];

    for (const el of candidates) {
      if (!el.className || typeof el.className !== 'string') continue;
      const firstClass = el.className.trim().split(/\s+/)[0];
      if (!firstClass) continue;

      const selector = `.${_escapeClass(firstClass)}`;
      if (knownSelectors.has(selector)) continue;
      if (seen.has(selector)) continue;
      seen.add(selector);

      const score = _scoreCandidate(el, userMessageEl);
      if (score > 0) scored.push({ selector, score });
    }

    if (scored.length === 0) return null;

    scored.sort((a, b) => b.score - a.score);
    const winner     = scored[0];
    const confidence = winner.score / MAX_POSSIBLE_SCORE;

    if (confidence >= DISCOVERY_CONFIDENCE_MIN) {
      console.info(
        `[Mnemostroma] discovery: found "${winner.selector}" confidence=${confidence.toFixed(2)}`
      );
      await updateSelectorsTable(hostname, winner.selector, confidence);
      return winner.selector;
    }

    console.debug(`[Mnemostroma] discovery: best candidate "${winner.selector}" confidence=${confidence.toFixed(2)} below threshold`);
    return null;

  } catch (err) {
    console.warn('[Mnemostroma] discovery: discoverSelector failed:', err.message);
    return null;
  }
}

/**
 * @param {string} hostname
 * @param {string|null} discoveredSelector
 * @param {number|null} confidence
 */
export async function updateSelectorsTable(
  hostname,
  discoveredSelector = null,
  confidence = null
) {
  try {
    const key = `selectors_db_${hostname}`;
    const db  = await _loadSelectorsDb(hostname);

    const currentClasses = new Set();
    document.querySelectorAll('div, article, section, main').forEach(el => {
      if (el.className && typeof el.className === 'string') {
        const firstClass = el.className.trim().split(/\s+/)[0];
        if (firstClass) currentClasses.add(`.${_escapeClass(firstClass)}`);
      }
    });

    sessionStorage.setItem(key, JSON.stringify({
        working:    discoveredSelector ?? db?.working ?? null,
        previous:   db?.current ?? [],
        current:    [...currentClasses],
        updated_at: Math.floor(Date.now() / 1000),
        confidence: confidence ?? db?.confidence ?? null,
    }));
  } catch { }
}
