export function parseJsonSafe(text) {
  try {
    return { ok: true, value: JSON.parse(text) };
  } catch {
    return { ok: false, value: null };
  }
}

export function makeParser(name, version, config) {
  return {
    name,
    version,
    allowlist: config.allowlist ?? null,
    matchRequest: config.matchRequest,
    extractUserInput: config.extractUserInput,
    extractConversationId: config.extractConversationId,
    parseDelta: config.parseDelta,
    finalize: config.finalize,
    classifyTurn: config.classifyTurn ?? (() => 'new_turn'),
  };
}

/** Returns true if the request meta passes the parser's allowlist constraints. */
export function isAllowed(parser, meta) {
  const al = parser?.allowlist;
  if (!al) return parser?.matchRequest?.(meta) ?? false;
  const urlObj = (() => { try { return new URL(meta.url); } catch { return null; } })();
  if (!urlObj) return false;
  if (al.hostname && urlObj.hostname !== al.hostname) return false;
  if (al.pathPrefix && !urlObj.pathname.startsWith(al.pathPrefix)) return false;
  if (al.methods && !al.methods.includes(meta.method)) return false;
  return true;
}
