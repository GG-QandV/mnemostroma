/** @file bridge.js — world: ISOLATED.
 *  Получает postMessage от index.js (world: MAIN) и пересылает в chrome.runtime. */

// Inline полифилл — не требует ESM import
const api = typeof browser !== 'undefined' ? browser : chrome;

const ALLOWED_TYPES = new Set([
  'COLLECT',
  'SITE_CHANGED',
  'SELECTOR_BROKEN',
  'FETCH_SELECTORS',
  'TRANSPORT_METRIC',
]);

window.addEventListener('message', (event) => {
  if (event.source !== window) return;
  if (event.origin !== window.location.origin) return;

  const msg = event.data;
  if (!msg || msg.__mnemo !== true) return;
  if (!ALLOWED_TYPES.has(msg.type)) return;

  // Shape validation: COLLECT must have hostname (string) and payload (object).
  if (msg.type === 'COLLECT') {
    if (typeof msg.hostname !== 'string' || !msg.hostname) return;
    if (!msg.payload || typeof msg.payload !== 'object') return;
  }

  const { __mnemo, ...payload } = msg;

  if (!api?.runtime?.sendMessage) {
    console.warn('[Mnemostroma] Extension context invalidated. Please refresh the page to reconnect.');
    return;
  }

  try {
    const promise = api.runtime.sendMessage(payload);
    if (promise && typeof promise.then === 'function') {
      promise
        .then(res => {
          if (msg.id) {
            window.postMessage({ __mnemo_reply: true, id: msg.id, res }, window.location.origin);
          }
        })
        .catch(err => {
          const errMsg = err?.message || String(err || '');
          if (msg.id) {
            window.postMessage({ __mnemo_reply: true, id: msg.id, error: errMsg }, window.location.origin);
          }
          if (errMsg.includes('context invalidated') || errMsg.includes('Extension context invalidated')) {
            console.warn('[Mnemostroma] Extension updated. Please refresh the page to reconnect.');
          } else {
            console.debug('[Mnemostroma] bridge: sendMessage failed:', errMsg);
          }
        });
    } else {
      console.debug('[Mnemostroma] bridge: sendMessage did not return a promise');
    }
  } catch (err) {
    const errMsg = err?.message || String(err || '');
    if (msg.id) {
      window.postMessage({ __mnemo_reply: true, id: msg.id, error: errMsg }, window.location.origin);
    }
    if (errMsg.includes('context invalidated') || errMsg.includes('Extension context invalidated')) {
      console.warn('[Mnemostroma] Extension updated. Please refresh the page to reconnect.');
    } else {
      console.warn('[Mnemostroma] bridge: sync error:', errMsg);
    }
  }
});

// Сигнализируем index.js что bridge готов принимать сообщения
window.postMessage({ __mnemo_bridge_ready: true }, window.location.origin);

// Инжект MAIN world скрипта как ES-модуля (т.к. content_scripts не поддерживают type: module)
const script = document.createElement('script');
script.type = 'module';
script.src = api.runtime.getURL('src/content/index.js');
(document.head || document.documentElement).appendChild(script);
