/** @file transport_capture.js
 *  Transport-first capture core (phase: mid skeleton).
 *  Provides deterministic request IDs, state transitions, timeout handling,
 *  and nav-epoch stale chunk protection.
 */

const EVENT_TYPES = new Set([
  'request_start',
  'user_input',
  'assistant_delta',
  'assistant_done',
  'request_abort',
  'request_error',
]);

export function validateTransportEvent(event) {
  return !!event && typeof event === 'object' && EVENT_TYPES.has(event.event_type);
}

export function buildRequestId({
  provider = 'unknown',
  method = 'GET',
  canonicalPath = '/',
  tabId = 'tab0',
  navEpoch = 0,
  seq = 0,
} = {}) {
  const input = `${provider}|${method}|${canonicalPath}|${tabId}|${navEpoch}|${seq}`;
  // Lightweight deterministic hash (FNV-1a variant) to avoid async crypto dependency.
  let hash = 2166136261;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return `req_${(hash >>> 0).toString(16)}`;
}

function createTimeoutMatrix(overrides = {}) {
  return {
    first_delta_timeout_ms: 12000,
    stream_idle_timeout_ms: 8000,
    finalize_timeout_ms: 4000,
    ...overrides,
  };
}

export function createTransportCapture({
  onFinalized = () => {},
  onMetric = () => {},
  provider = 'generic',
  tabId = 'tab0',
  timeoutOverrides = {},
} = {}) {
  let navEpoch = 0;
  let seq = 0;
  const requests = new Map();
  const t = createTimeoutMatrix(timeoutOverrides);

  function _setTimer(req, key, ms, fn) {
    clearTimeout(req.timers[key]);
    req.timers[key] = setTimeout(fn, ms);
  }

  function _clearTimers(req) {
    for (const key of Object.keys(req.timers)) clearTimeout(req.timers[key]);
  }

  function _ensureTerminal(req, nextState) {
    if (req.terminal) return false;
    req.terminal = true;
    req.state = nextState;
    _clearTimers(req);
    return true;
  }

  function setNavEpoch(nextEpoch) {
    navEpoch = nextEpoch;
  }

  function getNavEpoch() {
    return navEpoch;
  }

  function startRequest(meta = {}) {
    const request_id = buildRequestId({
      provider,
      method: meta.method ?? 'POST',
      canonicalPath: meta.canonicalPath ?? '/',
      tabId,
      navEpoch,
      seq: ++seq,
    });
    const req = {
      request_id,
      state: 'REQUEST_STARTED',
      navEpoch,
      user: '',
      assistant: '',
      terminal: false,
      timers: {},
    };
    requests.set(request_id, req);
    _setTimer(req, 'firstDelta', t.first_delta_timeout_ms, () => failRequest(request_id, 'first_delta_timeout'));
    return request_id;
  }

  function addUserInput(request_id, text) {
    const req = requests.get(request_id);
    if (!req || req.terminal) return;
    req.user = String(text ?? '');
  }

  function addAssistantDelta(request_id, textDelta, chunkEpoch = navEpoch) {
    const req = requests.get(request_id);
    if (!req || req.terminal) return { ok: false, reason: 'missing_request' };
    if (chunkEpoch !== req.navEpoch) {
      onMetric('stale_chunk_drop');
      return { ok: false, reason: 'stale_chunk' };
    }
    if (req.state === 'REQUEST_STARTED') req.state = 'STREAMING';
    req.assistant += String(textDelta ?? '');
    _setTimer(req, 'streamIdle', t.stream_idle_timeout_ms, () => doneRequest(request_id));
    return { ok: true };
  }

  function doneRequest(request_id) {
    const req = requests.get(request_id);
    if (!req || !_ensureTerminal(req, 'FINALIZED')) return false;
    const payload = {
      request_id,
      provider,
      nav_epoch: req.navEpoch,
      userText: req.user,
      assistantText: req.assistant,
      state: req.state,
      capture_source: 'transport',
    };
    onFinalized(payload);
    requests.delete(request_id);
    return true;
  }

  function abortRequest(request_id) {
    const req = requests.get(request_id);
    if (!req || !_ensureTerminal(req, 'ABORTED')) return false;
    requests.delete(request_id);
    return true;
  }

  function failRequest(request_id, reason = 'unknown') {
    const req = requests.get(request_id);
    if (!req || !_ensureTerminal(req, 'FAILED')) return false;
    onMetric('finalization_timeout_rate', reason);
    requests.delete(request_id);
    return true;
  }

  function getState(request_id) {
    return requests.get(request_id)?.state ?? null;
  }

  function stopAll() {
    for (const req of requests.values()) _clearTimers(req);
    requests.clear();
  }

  return {
    EVENT_TYPES,
    validateTransportEvent,
    startRequest,
    addUserInput,
    addAssistantDelta,
    doneRequest,
    abortRequest,
    failRequest,
    getState,
    setNavEpoch,
    getNavEpoch,
    stopAll,
  };
}

export function installFetchHook({
  parser,
  core,
  getNavEpoch = () => 0,
  onMetric = () => {},
} = {}) {
  if (!parser || !core || typeof window?.fetch !== 'function') return () => {};
  const origFetch = window.fetch.bind(window);

  window.fetch = async function transportCaptureFetch(input, init) {
    const url = typeof input === 'string' ? input : (input?.url ?? '');
    const method = (init?.method ?? 'GET').toUpperCase();
    const meta = { url, method };

    if (!parser.matchRequest(meta)) return origFetch(input, init);

    const requestText = typeof init?.body === 'string' ? init.body : '';
    const request_id = core.startRequest({
      method,
      canonicalPath: safePath(url),
    });
    const userInput = parser.extractUserInput(requestText);
    if (userInput) core.addUserInput(request_id, userInput);

    try {
      const response = await origFetch(input, init);
      const raw = await response.clone().text();
      const contentType = response.headers.get('content-type') || '';
      const deltas = [];

      if (contentType.includes('text/event-stream')) {
        const lines = raw.split('\n');
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const data = line.slice(5).trim();
          const parsed = parser.parseDelta(data);
          if (parsed?.textDelta) {
            deltas.push(parsed.textDelta);
            core.addAssistantDelta(request_id, parsed.textDelta, getNavEpoch());
          }
          if (parsed?.done) break;
          if (parsed?.control?.type === 'malformed') onMetric('parse_error');
        }
      } else {
        const parsed = parser.parseDelta(raw);
        if (parsed?.textDelta) {
          deltas.push(parsed.textDelta);
          core.addAssistantDelta(request_id, parsed.textDelta, getNavEpoch());
        } else if (raw && !parsed?.control) {
          // Non-stream fallback: preserve raw text only if parser made no explicit
          // control decision (MISSING_FIELD, SCHEMA_DRIFT, etc.).
          // If control is set the parser rejected this payload — do not write raw JSON.
          core.addAssistantDelta(request_id, raw, getNavEpoch());
          deltas.push(raw);
        }
      }

      const finalized = parser.finalize({ deltas });
      if (finalized?.assistantText && deltas.length === 0) {
        core.addAssistantDelta(request_id, finalized.assistantText, getNavEpoch());
      }
      core.doneRequest(request_id);
      return response;
    } catch (err) {
      onMetric('parse_error');
      core.failRequest(request_id, String(err?.message || err));
      throw err;
    }
  };

  return function uninstall() {
    window.fetch = origFetch;
  };
}

function safePath(url) {
  try {
    return new URL(url, window.location.origin).pathname || '/';
  } catch {
    return '/';
  }
}
