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

  if (!api?.runtime) return;

  try {
    api.runtime.sendMessage(payload)
      .then(res => {
        if (msg.id) {
          window.postMessage({ __mnemo_reply: true, id: msg.id, res }, window.location.origin);
        }
      })
      .catch(err =>
        console.debug('[Mnemostroma] bridge: sendMessage failed:', err.message)
      );
  } catch (err) {
    if (err.message.includes('context invalidated')) {
      console.warn('[Mnemostroma] Extension updated. Please refresh the page to reconnect.');
    } else {
      console.warn('[Mnemostroma] bridge: sync error:', err.message);
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
