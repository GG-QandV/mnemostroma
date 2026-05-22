// tests/unit/popup.test.js
import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'fs';
import path from 'path';

// Мокаем глобальные объекты chrome
globalThis.chrome = {
  storage: {
    local: {
      get: vi.fn(),
      set: vi.fn()
    }
  },
  alarms: {
    create: vi.fn()
  }
};

// Мокаем navigator.clipboard
globalThis.navigator = {
  clipboard: {
    writeText: vi.fn()
  }
};

// Глобальный mock fetch
globalThis.fetch = vi.fn();

// Читаем и адаптируем код popup.js
const popupCodePath = path.resolve(__dirname, '../../../mnemostroma/extension/popup.js');
let popupCode = fs.readFileSync(popupCodePath, 'utf8');
popupCode = popupCode.replace('async function refresh()', 'globalThis.refresh = async function refresh()');

describe('popup.js unit tests', () => {
  beforeEach(() => {
    document.body.innerHTML = `
      <span id="daemon-status"></span>
      <span id="queue-size"></span>
      <input id="mcp-url" />
      <button id="copy-btn"></button>
      <button id="retry-btn"></button>
    `;

    vi.resetAllMocks();

    // Дефолтный мок для chrome.storage.local.get
    chrome.storage.local.get.mockResolvedValue({
      mnemo_queue: []
    });

    // Дефолтный успешный мок fetch
    fetch.mockImplementation((url) => {
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok" })
        });
      }
      if (url.includes('/mcp-config')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            local_url: "http://127.0.0.1:8765/sse?token=abc",
            public_url: null
          })
        });
      }
      return Promise.reject(new Error("Unknown URL"));
    });

    // Выполняем скрипт в контексте глобального окружения
    new Function(popupCode)();
  });

  it('показывает local_url если public_url null', async () => {
    // Вызываем refresh() и ждем выполнения
    await globalThis.refresh();

    const mcpUrlInput = document.getElementById('mcp-url');
    expect(mcpUrlInput.value).toBe('http://127.0.0.1:8765/sse?token=abc');

    const daemonStatus = document.getElementById('daemon-status');
    expect(daemonStatus.textContent).toBe('● up');
    expect(daemonStatus.className).toBe('ok');
  });

  it('показывает public_url если есть', async () => {
    fetch.mockImplementation((url) => {
      if (url.includes('/health')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: "ok" })
        });
      }
      if (url.includes('/mcp-config')) {
        return Promise.resolve({
          ok: true,
          json: () => Promise.resolve({
            local_url: "http://127.0.0.1:8765/sse?token=abc",
            public_url: "https://xyz.serveo.net/sse?token=abc"
          })
        });
      }
      return Promise.reject(new Error("Unknown URL"));
    });

    await globalThis.refresh();

    const mcpUrlInput = document.getElementById('mcp-url');
    expect(mcpUrlInput.value).toBe('https://xyz.serveo.net/sse?token=abc');
  });

  it('daemon not running если fetch упал', async () => {
    fetch.mockRejectedValue(new Error('Network error'));

    await globalThis.refresh();

    const mcpUrlInput = document.getElementById('mcp-url');
    expect(mcpUrlInput.value).toBe('daemon not running');

    const daemonStatus = document.getElementById('daemon-status');
    expect(daemonStatus.textContent).toBe('● down');
    expect(daemonStatus.className).toBe('err');
  });

  it('копирует URL в буфер обмена при клике на copy-btn', async () => {
    await globalThis.refresh();

    const copyBtn = document.getElementById('copy-btn');
    expect(copyBtn.onclick).toBeDefined();

    // Имитируем клик
    copyBtn.onclick();

    expect(navigator.clipboard.writeText).toHaveBeenCalledWith('http://127.0.0.1:8765/sse?token=abc');
  });

  it('триггерит retry при клике на retry-btn', () => {
    const retryBtn = document.getElementById('retry-btn');
    
    // Клик на кнопку
    retryBtn.click();

    expect(chrome.alarms.create).toHaveBeenCalledWith('mnemo-retry', { delayInMinutes: 0 });
  });
});
