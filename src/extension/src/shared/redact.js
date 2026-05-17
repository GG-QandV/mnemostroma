/** Redaction utilities for debug logs. Never log raw tokens or auth headers. */

const TOKEN_RE = /\b(Bearer\s+[\w\-.~+/]+=*|sk-[A-Za-z0-9]{20,})\b/g;
const AUTH_HEADERS = new Set(['authorization', 'cookie', 'x-api-key', 'x-auth-token', 'x-mnemo-token']);

export function redactTokens(text) {
  if (typeof text !== 'string') return text;
  return text.replace(TOKEN_RE, '[REDACTED]');
}

export function redactHeaders(headers) {
  if (!headers || typeof headers !== 'object') return {};
  return Object.fromEntries(
    Object.entries(headers).map(([k, v]) =>
      AUTH_HEADERS.has(k.toLowerCase()) ? [k, '[REDACTED]'] : [k, v]
    )
  );
}
