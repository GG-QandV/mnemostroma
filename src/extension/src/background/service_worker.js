// src/background/service_worker.js
import {
  DAEMON_HEALTH_URL,
  HEALTH_CHECK_INTERVAL_S,
  SUPPORTED_SITES,
  SELECTORS_REMOTE_URL,
  DEFAULT_CAPTURE_MODE,
} from '../shared/constants.js';
import { postCollect } from '../shared/transport.js';
import { incrementMetric, METRIC_KEYS } from '../shared/metrics.js';
import api from '../shared/compat.js';

// ─── Contracts ────────────────────────────────────────────────────────────────
// transport.js MUST export:
//   export async function postCollect(payload) → Promise<boolean>
//   false = all retries exhausted, never throws
//
// bridge.js MUST send messages in exactly this shape:
//   { type: 'COLLECT',         hostname: string, payload: object }
//   { type: 'SITE_CHANGED',    hostname: string }
//   { type: 'SELECTOR_BROKEN', hostname: string }
//   { type: 'TRANSPORT_METRIC', hostname: string, metric: string }

// Reset mcpConfirmed only after this many consecutive health failures —
// avoids losing user preference on a single transient network hiccup
const HEALTH_FAIL_THRESHOLD = 2;

// Runtime counters (Phase 0) — reset on SW start
let _runtimeCounters = { success: 0, fallback: 0, error: 0 };

// ─── Badge ────────────────────────────────────────────────────────────────────

function setBadge({ text = '', color = '#22c55e' } = {}) {
  api.action.setBadgeText({ text });
  api.action.setBadgeBackgroundColor({ color });
}
function badgeGreen()  { setBadge({ text: '',  color: '#22c55e' }); }
function badgeYellow() { setBadge({ text: '!', color: '#eab308' }); }
function badgeRed()    { setBadge({ text: 'X', color: '#ef4444' }); } // ASCII — badge-safe across platforms

// ─── Fetch with timeout ───────────────────────────────────────────────────────
// AbortSignal.timeout() is MV3-safe: no setTimeout that can outlive SW sleep.
// Minimum: Chrome 103, Firefox 100 — both covered by manifest requirements §2.2

function fetchWithTimeout(url, ms) {
  return fetch(url, { signal: AbortSignal.timeout(ms) });
}

// ─── Health check ─────────────────────────────────────────────────────────────
// Module-level flag prevents parallel health checks within one SW activation.
// Resets naturally when SW sleeps — no stale lock possible across activations.

let _healthCheckInFlight = false;

async function runHealthCheck() {
  if (_healthCheckInFlight) return;
  _healthCheckInFlight = true;
  try {
    await _doHealthCheck();
  } finally {
    _healthCheckInFlight = false;
  }
}

async function _doHealthCheck() {
  try {
    const res  = await fetchWithTimeout(DAEMON_HEALTH_URL, 5000);
    const json = await res.json();
    const alive = json?.status === 'ok';
    const mcpConf = json?.mcpConfirmed === true;

    if (!alive) {
      await _handleDaemonDown();
      return;
    }

    // Daemon alive — reset fail counter, update mcpConfirmed
    await api.storage.local.set({ daemonAlive: true, healthFailCount: 0, mcpConfirmed: mcpConf });

    const { globalEnabled = true, lastPostOk = true } =
      await api.storage.local.get(['globalEnabled', 'lastPostOk']);

    if (!globalEnabled || !lastPostOk) badgeYellow(); else badgeGreen();

  } catch {
    await _handleDaemonDown();
  }
}

async function _handleDaemonDown() {
  const { healthFailCount = 0 } = await api.storage.local.get('healthFailCount');
  const newCount = healthFailCount + 1;

  const update = { daemonAlive: false, healthFailCount: newCount };

  // Only reset mcpConfirmed after N consecutive failures — not on first hiccup §8.3
  if (newCount >= HEALTH_FAIL_THRESHOLD) {
    update.mcpConfirmed = false;
  }

  await api.storage.local.set(update);
  badgeRed();
}

// ─── Defaults ─────────────────────────────────────────────────────────────────

async function mergeDefaults() {
  const existing = await api.storage.local.get([
    'globalEnabled', 'siteEnabled', 'daemonAlive',
    'mcpConfirmed', 'lastPostOk', 'healthFailCount',
  ]);

  const defaultSiteEnabled = Object.fromEntries(SUPPORTED_SITES.map(s => [s, true]));

  const scalar = {
    globalEnabled:   true,
    daemonAlive:     false,
    mcpConfirmed:    false,
    lastPostOk:      true,
    healthFailCount: 0,
    captureMode:     DEFAULT_CAPTURE_MODE,
  };

  const toSet = {};

  for (const [k, v] of Object.entries(scalar)) {
    if (existing[k] === undefined) toSet[k] = v;
  }

  // Deep merge siteEnabled: add new sites, preserve existing user preferences.
  // Uses SITES.some() — avoids JSON.stringify key-order fragility.
  const needsUpdate = SUPPORTED_SITES.some(s => (existing.siteEnabled ?? {})[s] === undefined);
  if (needsUpdate) {
    toSet.siteEnabled = { ...defaultSiteEnabled, ...(existing.siteEnabled ?? {}) };
  }

  if (Object.keys(toSet).length) await api.storage.local.set(toSet);
}

// ─── Install / update ─────────────────────────────────────────────────────────

api.runtime.onInstalled.addListener(async ({ reason }) => {
  if (reason === 'install' || reason === 'update') await mergeDefaults();
  await runHealthCheck();
});

// ─── Alarms ───────────────────────────────────────────────────────────────────
// Callback API — works in Chrome and Firefox MV3 (Promise API absent pre-FF120)

api.alarms.get('healthCheck', (existing) => {
  if (!existing) {
    api.alarms.create('healthCheck', { periodInMinutes: HEALTH_CHECK_INTERVAL_S / 60 });
  }
});

api.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === 'healthCheck') runHealthCheck();
});

// ─── Storage change → badge refresh ──────────────────────────────────────────
// Popup writes toggles directly to storage — SW reflects the change in badge §8.1
// Compare newValue !== oldValue to skip no-op writes and avoid extra health checks

api.storage.onChanged.addListener((changes) => {
  const globalChanged = 'globalEnabled' in changes &&
    changes.globalEnabled.newValue !== changes.globalEnabled.oldValue;
  const siteChanged = 'siteEnabled' in changes; // object diff skipped — always refresh
  if (globalChanged || siteChanged) runHealthCheck();
});

// ─── Messages ─────────────────────────────────────────────────────────────────

api.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handleMessage(msg)
    .then(r  => { try { sendResponse(r); }                               catch (_) {} })
    .catch(e => { try { sendResponse({ ok: false, error: String(e) }); } catch (_) {} });
  return true; // synchronous true — keeps port open for async response (MV3 required)
});

async function handleMessage(msg) {
  const { type } = msg;

  if (type === 'SELECTOR_BROKEN') {
    // Red takes priority over yellow — only set yellow if daemon is alive §8.1
    const { daemonAlive = true } = await api.storage.local.get('daemonAlive');
    if (daemonAlive) badgeYellow();
    return { ok: true };
  }

  if (type === 'SITE_CHANGED') {
    // Navigation signal only — do NOT trigger health check here.
    // SPA navigation fires this repeatedly; health check runs on its own alarm §6.5
    return { ok: true };
  }

  if (type === 'COLLECT') {
    return await handleCollect(msg);
  }

  if (type === 'FETCH_SELECTORS') {
    try {
      const res = await fetch(SELECTORS_REMOTE_URL);
      const data = await res.json();
      return { ok: true, data };
    } catch (e) {
      return { ok: false };
    }
  }

  if (type === 'TRANSPORT_METRIC') {
    return await handleTransportMetric(msg);
  }

  return { ok: false, error: 'unknown message type' };
}

async function handleCollect(msg) {
  const { hostname, payload } = msg;

  // Guard: bridge.js contract violation
  if (!hostname || !payload) {
    console.warn('[Mnemostroma] COLLECT missing hostname or payload', msg);
    return { ok: false, error: 'invalid message' };
  }

  const stored = await api.storage.local.get([
    'globalEnabled', 'siteEnabled', 'daemonAlive',
  ]);

  // Fast-path: skip POST if daemon known offline — saves up to 50s of retry delay
  if (stored.daemonAlive === false) {
    badgeRed();
    return { ok: false, dropped: true };
  }

  const globalEnabled = stored.globalEnabled !== false;
  const siteEnabled   = (stored.siteEnabled ?? {})[hostname] !== false;

  if (!globalEnabled || !siteEnabled) {
    badgeYellow(); // capture disabled — §8.1
    return { ok: false, dropped: true };
  }

  // Defensive wrap: transport.js contract requires no-throw, but guard anyway
  let success = false;
  try {
    success = await postCollect(payload);
  } catch (e) {
    console.warn('[Mnemostroma] postCollect threw unexpectedly:', e);
    success = false;
  }

  if (success) {
    // POST confirmed daemon is alive — reset fail state
    await api.storage.local.set({ lastPostOk: true, daemonAlive: true, healthFailCount: 0 });
    badgeGreen();

    // Increment metrics (Phase 0)
    _runtimeCounters.success++;
    const shortName = payload?.capture_meta?.provider || (msg.hostname ? msg.hostname.split('.')[0] : 'unknown');
    if (payload?.capture_source === 'transport') {
      await incrementMetric(shortName, METRIC_KEYS.TRANSPORT_SUCCESS);
    } else {
      await incrementMetric(shortName, METRIC_KEYS.DOM_FALLBACK);
    }

    return { ok: true };
  }

  // POST failed — update lastPostOk and refresh daemon status for accurate badge
  _runtimeCounters.error++;
  await api.storage.local.set({ lastPostOk: false });
  await runHealthCheck(); // will set badge red/yellow based on fresh daemon state
  return { ok: false };
}

async function handleTransportMetric(msg) {
  const shortName = msg.hostname ? msg.hostname.split('.')[0] : 'unknown';
  const m = msg.metric;
  if (m === 'parse_error') {
    await incrementMetric(shortName, METRIC_KEYS.PARSE_ERROR);
    return { ok: true };
  }
  if (m === 'finalization_timeout_rate') {
    await incrementMetric(shortName, METRIC_KEYS.TIMEOUT);
    return { ok: true };
  }
  if (m === 'stale_chunk_drop') {
    await incrementMetric(shortName, METRIC_KEYS.DUPLICATE_DROP);
    return { ok: true };
  }
  return { ok: false, error: 'unknown transport metric' };
}

// ─── Wake-up health check ─────────────────────────────────────────────────────
// Covers SW activations NOT triggered by install/update (alarm wake, message wake).
// _healthCheckInFlight guard serialises any concurrent call from onInstalled.
runHealthCheck();
