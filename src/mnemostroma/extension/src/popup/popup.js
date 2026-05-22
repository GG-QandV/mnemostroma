// src/popup/popup.js
// No ESM imports — popup does not support type="module" in Firefox MV3
// Inline compat polyfill per spec §7.10

const api = typeof browser !== 'undefined' ? browser : chrome;

const SUPPORTED_SITES = [
  'claude.ai', 'chatgpt.com', 'perplexity.ai',
  'gemini.google.com', 'deepseek.com',
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
