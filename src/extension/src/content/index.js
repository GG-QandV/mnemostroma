/** @file index.js — world: MAIN.
 *  Центральный контент-скрипт: DOM-наблюдение, сбор обменов, SPA-навигация.
 *  Общается с service worker через bridge.js (world: ISOLATED) via postMessage. */

import {
  SUPPORTED_SITES,
  HOSTNAME_SHORT,
  STREAM_END_SETTLE_MS,
  STREAM_END_TIMEOUT_MS,
  SESSION_IDLE_TIMEOUT_MS,
  CAPTURE_SOURCE_DOM,
  CAPTURE_SOURCE_TRANSPORT,
  CAPTURE_MODE_DOM_ONLY,
  CAPTURE_MODE_TRANSPORT_FIRST,
  CAPTURE_MODE_TRANSPORT_ONLY,
  DEFAULT_CAPTURE_MODE,
  CAPTURE_KILL_SWITCH_KEY,
  IS_MCP_TUNNELING_ENABLED,
} from '../shared/constants.js';
import { generateSessionId, generateExchangeId, generateRegenerateId } from '../shared/session.js';
import { extractArtifacts } from '../shared/artifacts.js';
import { getSelectors, checkSelector } from '../shared/selectors.js';
import { discoverSelector, updateSelectorsTable } from '../shared/discovery.js';
import { createTransportCapture, installFetchHook } from './transport_capture.js';
import { shouldEnableDomObserver } from '../shared/capture_mode.js';
import { getProviderParser } from './providers/index.js';

// ─── Глобальное состояние ───────────────────────────────────────────────────

const hostname  = window.location.hostname;
const shortName = HOSTNAME_SHORT[hostname] ?? hostname;

let adapter            = null;
let selectors          = null;
let sessionId          = null;
let chatId             = null;
let exchangeCounter    = 0;
let retryCounter       = 0;
let containerEl        = null;
let responseSelector   = null;
let pendingUserMessage = null;
let _idleTimer         = null;
let _observer          = null;   // ссылка на активный MutationObserver (патч #5)
let _streamActive      = false;  // флаг активного стрима (патч #1)
let _initialized       = false;
let _navEpoch          = 0;
let _transportCore     = null;
let _captureMode       = DEFAULT_CAPTURE_MODE;
let _uninstallFetchHook = null;
// Dedupe: tracks exchange counters already finalized by transport in transport_first mode.
const _transportFinalizedKeys = new Set();

// ─── Мост к service worker ──────────────────────────────────────────────────

function _sendMessage(msg) {
  window.postMessage(
    { __mnemo: true, ...msg },
    window.location.origin
  );
}

/** Ждём ACK от bridge.js что он готов принимать сообщения */
function _waitForBridge() {
  return new Promise(resolve => {
    const handler = (event) => {
      if (event.origin !== window.location.origin) return;
      if (event.data?.__mnemo_bridge_ready) {
        window.removeEventListener('message', handler);
        resolve();
      }
    };
    window.addEventListener('message', handler);
    setTimeout(resolve, 150); // fallback: bridge уже отправил ready до нашего listener
  });
}

// ─── Idle timer ─────────────────────────────────────────────────────────────

function _resetIdleTimer() {
  clearTimeout(_idleTimer);
  _idleTimer = setTimeout(() => {
    sessionId       = null;
    exchangeCounter = 0;
    retryCounter    = 0;
    chatId          = null;
    console.info('[Mnemostroma] session idle timeout — reset');
  }, SESSION_IDLE_TIMEOUT_MS);
}

// ─── Сборка payload ─────────────────────────────────────────────────────────

function _buildPayload({ userText, llmText, responseEl, isRegenerate }) {
  const exchangeId = isRegenerate
    ? generateRegenerateId(sessionId, exchangeCounter, retryCounter)
    : generateExchangeId(sessionId, exchangeCounter);

  return {
    type:    'COLLECT',
    hostname,
    payload: {
      session_id:  sessionId,
      chatId,
      exchangeId,
      url:         window.location.href,
      // TODO(restore): Раскомментировать когда бэкенд будет готов раздельно обрабатывать промпт юзера
      // text:        `user: ${userText ?? ''}\nassistant: ${llmText ?? ''}`,
      text:        llmText ?? '',
      timestamp:   new Date().toISOString(),
      isRegenerate,
      capture_source: CAPTURE_SOURCE_DOM,
      artifacts:   responseEl ? extractArtifacts(responseEl) : [],
    },
  };
}

function _buildTransportPayload({ userText, llmText }) {
  const exchangeId = generateExchangeId(sessionId, exchangeCounter);
  return {
    type: 'COLLECT',
    hostname,
    payload: {
      session_id: sessionId,
      chatId,
      exchangeId,
      url: window.location.href,
      // TODO(restore): Раскомментировать когда бэкенд внутри готов раздельно обрабатывать промпт юзера
      // text: `user: ${userText ?? ''}\nassistant: ${llmText ?? ''}`,
      text: llmText ?? '',
      timestamp: new Date().toISOString(),
      isRegenerate: false,
      capture_source: CAPTURE_SOURCE_TRANSPORT,
      artifacts: [],
    },
  };
}

function _readCaptureMode() {
  // RELEASE GUARD: If MCP network tunneling is globally disabled, force DOM-only mode for stability.
  if (!IS_MCP_TUNNELING_ENABLED) return CAPTURE_MODE_DOM_ONLY;

  if (localStorage.getItem(CAPTURE_KILL_SWITCH_KEY)) return CAPTURE_MODE_DOM_ONLY;
  const value = localStorage.getItem('mnemo_capture_mode');
  if (value === CAPTURE_MODE_DOM_ONLY || value === CAPTURE_MODE_TRANSPORT_FIRST || value === CAPTURE_MODE_TRANSPORT_ONLY) {
    return value;
  }
  return DEFAULT_CAPTURE_MODE;
}

function _initTransportCore() {
  const parser = getProviderParser(shortName);
  _transportCore = createTransportCapture({
    provider: shortName,
    tabId: 'tab0',
    onMetric: (name) => {
      // Mid phase: placeholder for transport metrics relay.
      if (name === 'stale_chunk_drop') {
        console.debug('[Mnemostroma] stale transport chunk dropped');
      }
      if (name === 'parse_error' || name === 'finalization_timeout_rate' || name === 'stale_chunk_drop') {
        _sendMessage({ type: 'TRANSPORT_METRIC', hostname, metric: name });
      }
    },
    onFinalized: ({ userText, assistantText }) => {
      const dedupeKey = `${sessionId}:${exchangeCounter}`;
      _transportFinalizedKeys.add(dedupeKey);
      exchangeCounter++;
      const payload = _buildTransportPayload({ userText, llmText: assistantText });
      _sendMessage(payload);
      _resetIdleTimer();
    },
  });
  _transportCore.setNavEpoch(_navEpoch);

  if (parser) {
    _uninstallFetchHook = installFetchHook({
      parser,
      core: _transportCore,
      getNavEpoch: () => _navEpoch,
      onMetric: (name) => _sendMessage({ type: 'TRANSPORT_METRIC', hostname, metric: name }),
    });
  }
}

// ─── Инициализация сессии ───────────────────────────────────────────────────

async function _initSession() {
  let newChatId = null;

  if (shortName === 'gemini') {
    // Шаг 1: DOM-атрибуты (§4.2)
    const threadEl = document.querySelector('[data-thread-id],[data-conversation-id]');
    newChatId = threadEl?.dataset.threadId ?? threadEl?.dataset.conversationId ?? null;

    // Шаг 3: sessionStorage — заполняется fetch-перехватчиком (шаг 2)
    if (!newChatId) {
      newChatId = sessionStorage.getItem('mnemo-gemini-chatid');
    }

    // Шаг 4: fallback UUID → сохранить в sessionStorage
    if (!newChatId) {
      newChatId = crypto.randomUUID();
      sessionStorage.setItem('mnemo-gemini-chatid', newChatId);
    }
  } else if (adapter?.extractChatId) {
    newChatId = adapter.extractChatId(window.location.href);
  }

  // Общий fallback: последний сегмент пути
  if (!newChatId) {
    const segments = new URL(window.location.href).pathname.split('/').filter(Boolean);
    newChatId = segments[segments.length - 1] ?? crypto.randomUUID();
  }

  if (newChatId === chatId) return; // та же беседа — не сбрасываем

  chatId          = newChatId;
  sessionId       = generateSessionId(shortName, chatId);
  exchangeCounter = 0;
  retryCounter    = 0;
  _streamActive   = false; // сброс флага стрима при смене сессии
  _resetIdleTimer();

  console.info(`[Mnemostroma] session init: ${sessionId}`);
}

// ─── Наблюдатель конца стрима ────────────────────────────────────────────────

function _onStreamEnd(responseEl) {
  const llmText  = adapter?.extractLlmResponse?.(responseEl) || responseEl.innerText || '';
  const userText = pendingUserMessage ?? '';
  pendingUserMessage = null;

  exchangeCounter++;
  retryCounter = 0;

  const payload = _buildPayload({ userText, llmText, responseEl, isRegenerate: false });
  _sendMessage(payload);
  _resetIdleTimer();
}

// ─── Regenerate ─────────────────────────────────────────────────────────────

function _onRegenerateCallback(responseEl) {
  const llmText  = adapter?.extractLlmResponse?.(responseEl) || responseEl.innerText || '';
  const userText = pendingUserMessage ?? '';

  retryCounter++;

  const payload = _buildPayload({ userText, llmText, responseEl, isRegenerate: true });
  _sendMessage(payload);
  _resetIdleTimer();
}

// ─── MutationObserver ───────────────────────────────────────────────────────

function _observeContainer() {
  // Патч #5: disconnect предыдущего observer перед переустановкой
  if (_observer) {
    _observer.disconnect();
    _observer = null;
  }

  // Патч #2: containerEl всегда определён (fallback на body)
  if (!containerEl || !responseSelector) return;

  _observer = new MutationObserver(() => {
    const stopBtn = selectors?.stopButton
      ? document.querySelector(selectors.stopButton)
      : null;

    // Патч #1: отслеживаем появление и исчезновение stopButton
    if (stopBtn && !_streamActive) {
      _streamActive = true; // стрим начался
      return;
    }

    if (!stopBtn && _streamActive) {
      _streamActive = false; // стрим закончился

      clearTimeout(_observeContainer._debounce);
      _observeContainer._debounce = setTimeout(() => {
        const allRes = containerEl.querySelectorAll(responseSelector);
        const responseEl = allRes.length ? allRes[allRes.length - 1] : null;
        if (!responseEl) return;

        // Патч #8: разделитель в guard против дублирования
        const captureKey = `${sessionId}:${exchangeCounter}`;
        if (responseEl.dataset.mnemoCaptured === captureKey) return;
        if (_transportFinalizedKeys.has(captureKey)) return;
        responseEl.dataset.mnemoCaptured = captureKey;

        _onStreamEnd(responseEl);
      }, STREAM_END_SETTLE_MS);
    }
  });

  _observer.observe(containerEl, { childList: true, subtree: true });
  console.info('[Mnemostroma] MutationObserver installed on', responseSelector);
}

// ─── Gemini fetch interceptor (world: MAIN, §3.2 / §13.3) ──────────────────

function _installGeminiFetchInterceptor() {
  if (shortName !== 'gemini') return;

  const _origFetch = window.fetch.bind(window);
  window.fetch = async function (input, init) {
    const response = await _origFetch(input, init);

    try {
      const url = typeof input === 'string' ? input : input?.url ?? '';
      if (url.includes('conversationId') || url.includes('/conversation')) {
        response.clone().json().then(data => {
          // Шаг 2 из §4.2: conversationId из Gemini API fetch
          const cid = data?.conversationId ?? data?.conversation?.id;
          if (cid) {
            sessionStorage.setItem('mnemo-gemini-chatid', cid);
            if (cid !== chatId) _onNavigation();
          }
        }).catch(() => {});
      }
    } catch (_) {}

    return response;
  };
}

// ─── SPA-навигация ──────────────────────────────────────────────────────────

async function _onNavigation() {
  await _initSession().catch(err =>
    console.warn('[Mnemostroma] navigation init error:', err)
  );

  // Патч #7: SITE_CHANGED только при навигации, не при init()
  _sendMessage({ type: 'SITE_CHANGED', hostname });
  _navEpoch++;
  if (_transportCore) _transportCore.setNavEpoch(_navEpoch);

  // Патч #6: переустановить observer при смене чата
  containerEl = document.querySelector(selectors?.container ?? 'body') ?? document.body;
  _observeContainer();
}

// ─── Точка входа ────────────────────────────────────────────────────────────

async function init() {
  if (_initialized) return;
  _initialized = true;

  // Ждём bridge.js
  await _waitForBridge();

  // Проверяем что сайт поддерживается
  if (!SUPPORTED_SITES.includes(hostname)) {
    console.info('[Mnemostroma] unsupported site, exiting');
    return;
  }

  _captureMode = _readCaptureMode();
  if (shortName === 'perplexity') {
    _captureMode = CAPTURE_MODE_DOM_ONLY;
  }
  if (_captureMode !== CAPTURE_MODE_DOM_ONLY) {
    _initTransportCore();
  }

  // Динамический импорт адаптера
  try {
    const mod = await import(`./adapters/${shortName}.js`);
    adapter = mod.default ?? mod;
  } catch (err) {
    console.warn('[Mnemostroma] adapter load failed:', err.message);
  }

  // Перехватчик для Gemini (до getSelectors, до _initSession)
  _installGeminiFetchInterceptor();

  // Загрузка селекторов
  selectors = await getSelectors(hostname);

  // Проверка рабочего селектора / discovery
  const selectorOk = await checkSelector(hostname, selectors?.responseContainer);
  if (!selectorOk) {
    const discovered = await discoverSelector(hostname);
    if (discovered) {
      await updateSelectorsTable(hostname, discovered);
      selectors = await getSelectors(hostname); // перечитать с обновлённым
    }
  }

  responseSelector = selectors?.responseContainer ?? null;
  // Патч #2: всегда fallback на body
  containerEl = document.querySelector(selectors?.container ?? 'body') ?? document.body;

  // Инициализация сессии
  await _initSession();

  // Подписка на регенерацию
  if (adapter?.onRegenerate) {
    adapter.onRegenerate(_onRegenerateCallback);
  }

  // Патч #4: Grok — submit listener с STREAM_END_TIMEOUT_MS
  if (shortName === 'grok' && adapter?.initSubmitListener) {
    adapter.initSubmitListener(() => {
      _savePendingUserMessage();
      setTimeout(() => {
        const responseEl = containerEl?.querySelector(responseSelector);
        if (!responseEl) return;
        const captureKey = `${sessionId}:${exchangeCounter}`;
        if (responseEl.dataset.mnemoCaptured === captureKey) return;
        responseEl.dataset.mnemoCaptured = captureKey;
        _onStreamEnd(responseEl);
      }, STREAM_END_TIMEOUT_MS);
    });
  } else if (adapter?.initSubmitListener) {
    adapter.initSubmitListener(_savePendingUserMessage);
  }

  // User message через keydown для non-Grok сайтов (§9.5)
  if (selectors?.userMessage && shortName !== 'grok') {
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        const msgEl = document.querySelector(selectors.userMessage);
        if (msgEl) {
          pendingUserMessage = msgEl.innerText?.trim() ?? null;
        }
      }
    }, { capture: true });
  }

  // DOM observer (disabled only in strict transport_only mode)
  if (shouldEnableDomObserver(_captureMode)) {
    _observeContainer();
  }

  // SPA-навигация: history override — строго внутри init()
  const _origPushState    = history.pushState.bind(history);
  const _origReplaceState = history.replaceState.bind(history);

  history.pushState = function (...args) {
    _origPushState(...args);
    _onNavigation();
  };
  history.replaceState = function (...args) {
    _origReplaceState(...args);
    _onNavigation();
  };

  window.addEventListener('popstate', _onNavigation);

  console.info(`[Mnemostroma] init complete on ${hostname}`);
}

// ─── Вспомогательные ────────────────────────────────────────────────────────

function _savePendingUserMessage() {
  if (adapter?.extractUserMessage) {
    pendingUserMessage = adapter.extractUserMessage();
  }
}

init().catch(err => console.error('[Mnemostroma] init failed:', err));
