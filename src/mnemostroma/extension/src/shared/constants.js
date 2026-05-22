/** @file constants.js — Global constants for the Mnemostroma extension */

// Сетевые адреса — extension → observe app (8766, plain HTTP)
export const DAEMON_HEALTH_URL    = 'http://127.0.0.1:8766/health';
export const COLLECT_URL          = 'http://127.0.0.1:8766/observe';
export const SELECTORS_REMOTE_URL = 'https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/selectors.json';

// Тайминги (мс)
export const SELECTORS_CACHE_TTL_MS  = 86_400_000; // 24 часа
export const STREAM_END_SETTLE_MS    = 150;
export const STREAM_END_TIMEOUT_MS   = 1_500;       // только Grok (v1.1)
export const TRANSPORT_TIMEOUT_MS    = 5_000;
export const SESSION_IDLE_TIMEOUT_MS = 1_800_000;   // 30 минут

// Transport retry (мс) — длина массива = кол-во попыток
// NOTE: задержки не применяются в MV3 SW (setTimeout умирает при sleep SW)
export const TRANSPORT_RETRY_DELAYS = [5_000, 15_000, 30_000];

// Health check
export const HEALTH_CHECK_INTERVAL_S = 30;

// Discovery
export const DISCOVERY_CONFIDENCE_MIN = 0.8;

// MCP-сайты (только они показывают предупреждение MCP в popup)
export const MCP_SITES = [
  'claude.ai',
  'chatgpt.com',
  'perplexity.ai',
  'www.perplexity.ai',
];

// Все поддерживаемые сайты v1.0 (grok.com — v1.1)
export const SUPPORTED_SITES = [
  'claude.ai',
  'chatgpt.com',
  'chat.openai.com',
  'perplexity.ai',
  'www.perplexity.ai',
  'gemini.google.com',
  'deepseek.com',
  'chat.deepseek.com',
  'grok.com',
  'x.com',
];

// Приведение hostname к короткой форме для session_id
export const HOSTNAME_SHORT = {
  'claude.ai':          'claude',
  'chatgpt.com':        'chatgpt',
  'chat.openai.com':    'chatgpt',
  'perplexity.ai':      'perplexity',
  'www.perplexity.ai':  'perplexity',
  'gemini.google.com':  'gemini',
  'deepseek.com':       'deepseek',
  'chat.deepseek.com':  'deepseek',
  'grok.com':           'grok',
  'x.com':              'grok',
};

// Capture Modes (Phase 0 — Roadmap)
export const CAPTURE_MODE_DOM_ONLY       = 'dom_only';
export const CAPTURE_MODE_TRANSPORT_FIRST = 'transport_first';
export const CAPTURE_MODE_TRANSPORT_ONLY  = 'transport_only';

// ─── RELEASE GUARD (STABILITY SHARDS) ─────────────────────────────────────────
// Controls the availability of DOM-independent MCP network tunneling (Phase 3/4).
// - Development/Beta (v2.1.5): Set to true (active for field tests & debug).
// - Stable Production (v2.0.5): Must be set to false (disabled for public safety).
export const IS_MCP_TUNNELING_ENABLED = true; 

export const DEFAULT_CAPTURE_MODE = IS_MCP_TUNNELING_ENABLED 
  ? CAPTURE_MODE_TRANSPORT_FIRST 
  : CAPTURE_MODE_DOM_ONLY;

// Kill-switch: localStorage key that forces dom_only regardless of DEFAULT_CAPTURE_MODE.
// Set to any truthy string to activate.
export const CAPTURE_KILL_SWITCH_KEY = 'mnemo_kill_switch';

// Capture Sources (Phase 0)
export const CAPTURE_SOURCE_DOM       = 'dom_fallback';
export const CAPTURE_SOURCE_TRANSPORT = 'transport';
