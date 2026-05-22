// tests/unit/popup.test.js
import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'fs';
import path from 'path';

// Мокаем глобальные объекты chrome
globalThis.chrome = {
  runtime: {
    getManifest: vi.fn(() => ({ version: '1.2.3' }))
  },
  tabs: {
    query: vi.fn()
  },
  storage: {
    local: {
      get: vi.fn(),
      set: vi.fn()
    },
    onChanged: {
      addListener: vi.fn()
    }
  }
};

// Читаем код popup.js
const popupCodePath = path.resolve(__dirname, '../../src/popup/popup.js');
const popupCode = fs.readFileSync(popupCodePath, 'utf8');

describe('popup.js unit tests', () => {
  beforeEach(() => {
    // Создаем DOM-структуру, соответствующую реальному popup.html
    document.body.innerHTML = `
      <div id="status-dot" class="status-dot"></div>
      <span id="status-text"></span>
      <div id="mcp-warning"></div>
      <input type="checkbox" id="toggle-global" />
      <div id="sites-list"></div>
      <span id="version"></span>
      <span id="footer-version"></span>
      <a id="docs-link"></a>
      <a id="mcp-link"></a>
    `;

    vi.resetAllMocks();

    // Настройка дефолтных моков
    chrome.runtime.getManifest.mockReturnValue({ version: '1.2.3' });
    chrome.tabs.query.mockResolvedValue([{ url: 'https://claude.ai/chat/123' }]);
    chrome.storage.local.get.mockResolvedValue({
      daemonAlive: true,
      mcpConfirmed: true,
      globalEnabled: true,
      siteEnabled: { 'claude.ai': true }
    });
  });

  it('инициализирует статические элементы и версию из манифеста', () => {
    new Function('chrome', popupCode)(chrome);

    const versionEl = document.getElementById('version');
    const footerVerEl = document.getElementById('footer-version');
    const docsLinkEl = document.getElementById('docs-link');
    const mcpLinkEl = document.getElementById('mcp-link');

    expect(versionEl.textContent).toBe('v1.2.3');
    expect(footerVerEl.textContent).toBe('1.2.3');
    expect(docsLinkEl.href).toContain('github.com');
    expect(mcpLinkEl.href).toContain('SETUP-MCP.md');
  });

  it('корректно отображает статус "Daemon connected" при активном демоне и MCP', async () => {
    new Function('chrome', popupCode)(chrome);

    // Даем микротаску выполниться для асинхронного рендеринга
    await new Promise(resolve => setTimeout(resolve, 0));

    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const mcpWarning = document.getElementById('mcp-warning');

    expect(statusDot.className).toBe('status-dot green');
    expect(statusText.textContent).toBe('Daemon connected');
    expect(mcpWarning.classList.contains('visible')).toBe(false);
  });

  it('показывает предупреждение MCP, если сайт поддерживает MCP, но он не подтвержден', async () => {
    chrome.storage.local.get.mockResolvedValue({
      daemonAlive: true,
      mcpConfirmed: false,
      globalEnabled: true,
      siteEnabled: {}
    });

    new Function('chrome', popupCode)(chrome);
    await new Promise(resolve => setTimeout(resolve, 0));

    const statusDot = document.getElementById('status-dot');
    const statusText = document.getElementById('status-text');
    const mcpWarning = document.getElementById('mcp-warning');

    expect(statusDot.className).toBe('status-dot yellow');
    expect(statusText.textContent).toBe('Daemon connected · MCP not detected');
    expect(mcpWarning.classList.contains('visible')).toBe(true);
  });

  it('переключает глобальную активность и сохраняет состояние', async () => {
    new Function('chrome', popupCode)(chrome);
    await new Promise(resolve => setTimeout(resolve, 0));

    const toggleGlobal = document.getElementById('toggle-global');
    expect(toggleGlobal.checked).toBe(true);

    // Имитируем переключение пользователем
    toggleGlobal.checked = false;
    toggleGlobal.dispatchEvent(new Event('change'));

    expect(chrome.storage.local.set).toHaveBeenCalledWith({ globalEnabled: false });
  });

  it('отрисовывает список сайтов с корректными чекбоксами', async () => {
    new Function('chrome', popupCode)(chrome);
    await new Promise(resolve => setTimeout(resolve, 0));

    const sitesList = document.getElementById('sites-list');
    const checkboxes = sitesList.querySelectorAll('input[type="checkbox"]');
    
    // В списке должно быть 5 поддерживаемых сайтов
    expect(checkboxes.length).toBe(5);

    const claudeCheckbox = Array.from(checkboxes).find(cb => cb.dataset.site === 'claude.ai');
    expect(claudeCheckbox).toBeDefined();
    expect(claudeCheckbox.checked).toBe(true);
  });
});
