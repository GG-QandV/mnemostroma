// src/popup/popup.js
// No ESM imports — popup does not support type="module" in Firefox MV3
// Inline compat polyfill per spec §7.10

const api = typeof browser !== 'undefined' ? browser : chrome;

const SUPPORTED_SITES = [
  'claude.ai', 'chatgpt.com', 'perplexity.ai',
  'gemini.google.com', 'deepseek.com', 'grok.com',
];
const MCP_SITES = ['claude.ai', 'chatgpt.com', 'perplexity.ai'];

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const statusDot    = document.getElementById('status-dot');
const statusText   = document.getElementById('status-text');
const mcpWarning   = document.getElementById('mcp-warning');
const toggleGlobal = document.getElementById('toggle-global');
const sitesList    = document.getElementById('sites-list');
const version      = document.getElementById('version');
const footerVer    = document.getElementById('footer-version');
const docsLink     = document.getElementById('docs-link');
const mcpLink      = document.getElementById('mcp-link');

// ─── Init static ─────────────────────────────────────────────────────────────

const manifest = api.runtime.getManifest();
const ver = manifest.version;
version.textContent   = `v${ver}`;
footerVer.textContent = ver;
docsLink.href = 'https://github.com/mnemostroma/extension#readme';
mcpLink.href  = 'https://github.com/mnemostroma/extension/blob/main/docs/SETUP-MCP.md';

// ─── Hostname cache ───────────────────────────────────────────────────────────
// Cached once — tabs.query is async and called on every render otherwise

let _hostname = null;

async function _getHostname() {
  if (_hostname) return _hostname;
  try {
    const [tab] = await api.tabs.query({ active: true, currentWindow: true });
    if (tab?.url) _hostname = new URL(tab.url).hostname;
  } catch (_) {}
  return _hostname;
}

// ─── Render status ────────────────────────────────────────────────────────────

function renderStatus(daemonAlive, mcpConfirmed, hostname) {
  if (!daemonAlive) {
    statusDot.className    = 'status-dot red';
    statusText.textContent = 'Daemon offline';
    mcpWarning.classList.remove('visible');
    return;
  }

  const isMcpSite = hostname && MCP_SITES.includes(hostname);
  if (isMcpSite && !mcpConfirmed) {
    statusDot.className    = 'status-dot yellow';
    statusText.textContent = 'Daemon connected · MCP not detected';
    mcpWarning.classList.add('visible');
    return;
  }

  statusDot.className    = 'status-dot green';
  statusText.textContent = 'Daemon connected';
  mcpWarning.classList.remove('visible');
}

// ─── Render per-site toggles ──────────────────────────────────────────────────

function renderSites(siteEnabled, globalEnabled) {
  sitesList.innerHTML = '';
  for (const site of SUPPORTED_SITES) {
    const enabled = siteEnabled[site] !== false;

    const row   = document.createElement('div');
    row.className = 'toggle-row';

    const label = document.createElement('span');
    label.className = 'toggle-label' + (globalEnabled ? '' : ' muted');
    label.textContent = site;

    const lbl   = document.createElement('label');
    lbl.className = 'toggle';

    const input = document.createElement('input');
    input.type     = 'checkbox';
    input.checked  = enabled;
    input.disabled = !globalEnabled;
    input.dataset.site = site;

    input.addEventListener('change', async () => {
      const { siteEnabled: current = {} } = await api.storage.local.get('siteEnabled');
      await api.storage.local.set({
        siteEnabled: { ...current, [site]: input.checked },
      });
    });

    const track = document.createElement('div');
    track.className = 'toggle-track';

    lbl.appendChild(input);
    lbl.appendChild(track);
    row.appendChild(label);
    row.appendChild(lbl);
    sitesList.appendChild(row);
  }
}

// ─── Full render ──────────────────────────────────────────────────────────────

async function render() {
  const stored = await api.storage.local.get([
    'daemonAlive', 'mcpConfirmed', 'globalEnabled', 'siteEnabled',
  ]);

  const daemonAlive   = stored.daemonAlive   ?? false;
  const mcpConfirmed  = stored.mcpConfirmed  ?? false;
  const globalEnabled = stored.globalEnabled !== false;
  const siteEnabled   = stored.siteEnabled   ?? {};

  const hostname = await _getHostname();

  renderStatus(daemonAlive, mcpConfirmed, hostname);
  renderSites(siteEnabled, globalEnabled);
  toggleGlobal.checked = globalEnabled;
}

// ─── Global toggle ────────────────────────────────────────────────────────────

toggleGlobal.addEventListener('change', async () => {
  const globalEnabled = toggleGlobal.checked;
  await api.storage.local.set({ globalEnabled });

  // Update site toggles disabled state
  sitesList.querySelectorAll('input[type="checkbox"]').forEach(input => {
    input.disabled = !globalEnabled;
    const labelEl = input.closest('.toggle-row')?.querySelector('.toggle-label');
    if (labelEl) labelEl.className = 'toggle-label' + (globalEnabled ? '' : ' muted');
  });

  // Update status dot — capture off = yellow if daemon alive
  const { daemonAlive = false, mcpConfirmed = false } =
    await api.storage.local.get(['daemonAlive', 'mcpConfirmed']);
  renderStatus(daemonAlive, mcpConfirmed, _hostname);
});

// ─── Live update while popup is open ─────────────────────────────────────────

api.storage.onChanged.addListener((changes) => {
  if ('daemonAlive'   in changes ||
      'mcpConfirmed'  in changes ||
      'globalEnabled' in changes ||
      'siteEnabled'   in changes) {
    render();
  }
});

// ─── Boot ─────────────────────────────────────────────────────────────────────

render();

// ─── Tunnel ───────────────────────────────────────────────────────────────────

const OBSERVE_PORT_PRIMARY = 8769;   // OAuth adapter (новый)
const OBSERVE_PORT_LEGACY   = 8766;  // Legacy adapter (старый)
const OBSERVE_TIMEOUT_MS    = 1500;  // Таймаут на все запросы к Observe API
const TUNNEL_POLL_MS        = 1500;

let _tunnelPolling = null;

function _tunnelShowState(state) {
  // state: "stopped" | "starting" | "running"
  document.getElementById("tunnel-stopped") .classList.toggle("hidden", state !== "stopped");
  document.getElementById("tunnel-starting").classList.toggle("hidden", state !== "starting");
  document.getElementById("tunnel-running") .classList.toggle("hidden", state !== "running");
}

async function observeFetch(path, options = {}) {
  let lastError = null;
  const ports = [OBSERVE_PORT_PRIMARY, OBSERVE_PORT_LEGACY];
  for (const port of ports) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), OBSERVE_TIMEOUT_MS);
    try {
      const res = await fetch(
        `http://127.0.0.1:${port}${path}`,
        { ...options, signal: controller.signal }
      );
      clearTimeout(timer);
      if (!res.ok) {
        lastError = new Error(`HTTP ${res.status} from port ${port}`);
        continue;
      }
      return res;
    } catch (e) {
      clearTimeout(timer);
      lastError = e;
    }
  }
  throw lastError || new Error("observeFetch: all ports failed");
}

async function _fetchTunnelStatus() {
  try {
    const r = await observeFetch("/tunnel/status");
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

function _escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function _copyAndFlash(text, message) {
  if (!text) return;
  navigator.clipboard.writeText(text)
    .then(() => {
      const hint = document.getElementById("copy-hint");
      if (!hint) return;
      hint.textContent = message;
      hint.classList.remove("hidden");
      setTimeout(() => hint.classList.add("hidden"), 2500);
    })
    .catch(err => console.warn("clipboard write failed:", err));
}

function _renderTunnelChats(chats) {
  const container = document.getElementById("tunnel-chats-container");
  if (!container) return;

  // Заменяем ноду целиком — сбрасывает все старые event listeners
  const fresh = container.cloneNode(false);
  container.parentNode.replaceChild(fresh, container);

  chats.forEach(chat => {
    const row = document.createElement("div");
    row.className = "chat-row";

    const tokenBtn = chat.needs_token
      ? `<button class="btn-copy-token btn-small"
                 data-token="${_escapeHtml(chat.token ?? "")}"
                 title="Copy token for ${_escapeHtml(chat.label)}">📋 Token</button>`
      : "";

    row.innerHTML = `
      <div class="chat-label">${chat.icon} ${_escapeHtml(chat.label)}</div>
      <div class="chat-url-text" title="${_escapeHtml(chat.full_url)}">${_escapeHtml(chat.full_url)}</div>
      <div class="chat-actions">
        <button class="btn-copy-url btn-small"
                data-url="${_escapeHtml(chat.full_url)}"
                title="Copy URL for ${_escapeHtml(chat.label)}">📋 Copy URL</button>
        ${tokenBtn}
      </div>
      <div class="chat-hint">${_escapeHtml(chat.hint)}</div>
    `;
    fresh.appendChild(row);
  });

  // Один delegated listener на контейнер
  fresh.addEventListener("click", e => {
    const u = e.target.closest(".btn-copy-url");
    const t = e.target.closest(".btn-copy-token");
    if (u) _copyAndFlash(u.dataset.url,   "✓ URL copied!");
    if (t) _copyAndFlash(t.dataset.token, "✓ Token copied!");
  });
}

function _stopPolling() {
  if (_tunnelPolling) { clearInterval(_tunnelPolling); _tunnelPolling = null; }
}

async function _refreshTunnel() {
  const data = await _fetchTunnelStatus();
  const tunnelRing = document.getElementById('tunnel-ring');

  if (!data) {
    if (tunnelRing) tunnelRing.className = 'tunnel-ring';
    _tunnelShowState("stopped");
    return;
  }

  // Обновление классов ободка (Часть 3.4 спецификации)
  if (tunnelRing) {
    if (data.active && data.url) {
      tunnelRing.className = 'tunnel-ring active';
    } else if (data.pid) {
      tunnelRing.className = 'tunnel-ring stale';
    } else {
      tunnelRing.className = 'tunnel-ring';
    }
  }

  if (data.running) {
    const display = document.getElementById("tunnel-url-display");
    if (display) {
      const url   = data.url || "";
      const short = url.replace("https://", "").slice(0, 38);
      display.textContent = short + (url.length > 42 ? "…" : "");
      display.title = url;
    }
    _renderTunnelChats(data.chats || []);
    _tunnelShowState("running");
  } else {
    _tunnelShowState("stopped");
  }
}

// ─── Tunnel error UI (Fix E) ────────────────────────────────────────────────

function _showTunnelError(message) {
  const el = document.getElementById("tunnel-error");
  if (!el) return;
  el.textContent = message;
  el.classList.remove("hidden");
  clearTimeout(el._hideTimer);
  el._hideTimer = setTimeout(() => el.classList.add("hidden"), 6000);
}

async function _tunnelAction(action) {
  const btn = document.getElementById(`btn-${action}-tunnel`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = action === "start" ? "Starting…" : "Stopping…";
  }
  try {
    await observeFetch(`/tunnel/${action}`, { method: "POST" });
    if (action === "start") {
      _tunnelShowState("starting");
      if (!_tunnelPolling) _tunnelPolling = setInterval(_refreshTunnel, TUNNEL_POLL_MS);
    } else {
      const tunnelRing = document.getElementById("tunnel-ring");
      if (tunnelRing) tunnelRing.className = "tunnel-ring";
      _stopPolling();
      _tunnelShowState("stopped");
    }
  } catch (e) {
    _showTunnelError(
      action === "start" ? `Tunnel start failed: ${e.message}` : `Tunnel stop failed: ${e.message}`
    );
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = action === "start" ? "▶ Start Tunnel" : "⏹";
    }
  }
}

document.getElementById("btn-start-tunnel")?.addEventListener("click", () => _tunnelAction("start"));
document.getElementById("btn-stop-tunnel")?.addEventListener("click", () => _tunnelAction("stop"));

document.getElementById("btn-copy-tunnel-url")?.addEventListener("click", () => {
  const el = document.getElementById("tunnel-url-display");
  if (el && el.title) _copyAndFlash(el.title, "✓ URL copied!");
});

window.addEventListener("unload", _stopPolling);

// Запускаем непрерывный опрос, пока открыт popup, чтобы ободок обновлялся динамически
_refreshTunnel();
_tunnelPolling = setInterval(_refreshTunnel, TUNNEL_POLL_MS);
