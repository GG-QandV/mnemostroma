// ==UserScript==
// @name         Mnemostroma AI Interceptor
// @namespace    https://github.com/GG-QandV/mnemostroma
// @version      1.0.0
// @description  Перехватывает ответы AI-платформ и отправляет в Mnemostroma /capture
// @author       Mnemostroma
// @match        *://chatgpt.com/*
// @match        *://chat.openai.com/*
// @match        *://gemini.google.com/*
// @match        *://grok.x.ai/*
// @match        *://chat.deepseek.com/*
// @match        *://claude.ai/*
// @match        *://perplexity.ai/*
// @grant        GM_xmlhttpRequest
// @connect      localhost
// @run-at       document-start
// ==/UserScript==

(() => {
  'use strict';

  const CAPTURE_URL = 'https://127.0.0.1:8767/capture';
  const MIN_LENGTH   = 20; // фильтр мусора

  // ── Отправка в демон ──────────────────────────────────────────────────

  function sendToMnemostroma(platform, text, sessionId) {
    if (!text || text.length < MIN_LENGTH) return;
    GM_xmlhttpRequest({
      method:  'POST',
      url:     CAPTURE_URL,
      headers: { 'Content-Type': 'application/json' },
      data:    JSON.stringify({ text: text.trim(), session_id: sessionId }),
      // самоподписанный CA — игнорируем ошибку TLS в Tampermonkey
      anonymous: true,
      onerror: () => {},
      onload:  () => {}
    });
  }

  function makeSessionId(platform) {
    const d = new Date().toISOString().slice(0, 10);
    return `${platform}-${d}-${Math.random().toString(36).slice(2, 7)}`;
  }

  // ── SSE-парсеры ───────────────────────────────────────────────────────

  // Накапливает неполные строки между чанками
  function makeLineBuffer() {
    let tail = '';
    return {
      feed(chunk) {
        const combined = tail + chunk;
        const lines = combined.split('\n');
        tail = lines.pop(); // последняя строка — возможно, обрезана
        return lines;
      },
      flush() { const l = tail; tail = ''; return l ? [l] : []; }
    };
  }

  // OpenAI-формат: data: {"choices":[{"delta":{"content":"..."}}]}
  async function openAIParser(response, platform) {
    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    const buf     = makeLineBuffer();
    const sid     = makeSessionId(platform);
    let   full    = '';

    while (true) {
      const { done, value } = await reader.read();
      const lines = done ? buf.flush() : buf.feed(decoder.decode(value, { stream: true }));

      for (const line of lines) {
        if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
        try {
          const delta = JSON.parse(line.slice(6))?.choices?.[0]?.delta?.content;
          if (delta) full += delta;
        } catch (_) {}
      }

      if (done) break;
    }

    sendToMnemostroma(platform, full, sid);
  }

  // Gemini-формат (web): массив JSON-объектов, не SSE
  // Реальный формат gemini.google.com отличается от публичного API —
  // пробуем оба варианта
  async function geminiParser(response, platform) {
    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    const buf     = makeLineBuffer();
    const sid     = makeSessionId(platform);
    let   full    = '';

    while (true) {
      const { done, value } = await reader.read();
      const lines = done ? buf.flush() : buf.feed(decoder.decode(value, { stream: true }));

      for (const line of lines) {
        // Публичный API формат
        if (line.startsWith('data: ')) {
          try {
            const json = JSON.parse(line.slice(6));
            const t = json?.candidates?.[0]?.content?.parts?.[0]?.text;
            if (t) full += t;
          } catch (_) {}
          continue;
        }
        // Внутренний web-формат: строки вида [[[...,"text",...],...]]
        if (line.startsWith('[[[')) {
          try {
            const arr = JSON.parse(line);
            const t = arr?.[0]?.[2]?.[0]?.[1];
            if (typeof t === 'string') full += t;
          } catch (_) {}
        }
      }

      if (done) break;
    }

    sendToMnemostroma(platform, full, sid);
  }

  // Claude.ai формат: event: content_block_delta / data: {"delta":{"text":"..."}}
  async function claudeParser(response, platform) {
    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    const buf     = makeLineBuffer();
    const sid     = makeSessionId(platform);
    let   full    = '';

    while (true) {
      const { done, value } = await reader.read();
      const lines = done ? buf.flush() : buf.feed(decoder.decode(value, { stream: true }));

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const json = JSON.parse(line.slice(6));
          if (json?.type === 'content_block_delta' && json?.delta?.text) {
            full += json.delta.text;
          }
        } catch (_) {}
      }

      if (done) break;
    }

    sendToMnemostroma(platform, full, sid);
  }

  // ── Роутер платформ ───────────────────────────────────────────────────

  const PLATFORM_MAP = {
    'chatgpt.com':        { name: 'chatgpt',    parser: openAIParser  },
    'chat.openai.com':    { name: 'chatgpt',    parser: openAIParser  },
    'chat.deepseek.com':  { name: 'deepseek',   parser: openAIParser  },
    'grok.x.ai':          { name: 'grok',       parser: openAIParser  },
    'perplexity.ai':      { name: 'perplexity', parser: openAIParser  },
    'gemini.google.com':  { name: 'gemini',     parser: geminiParser  },
    'claude.ai':          { name: 'claude',     parser: claudeParser  },
  };

  // URL-фильтр: пропускаем только запросы к AI-эндпоинтам
  function isAiEndpoint(url) {
    return (
      url.includes('/completions')       ||
      url.includes('/generateContent')   ||
      url.includes('/streamGenerateContent') ||
      url.includes('/conversation')      ||
      url.includes('/append_message')    ||
      url.includes('/chat/completions')  ||
      url.includes('/api/ask')
    );
  }

  // ── fetch override ────────────────────────────────────────────────────

  const _fetch = window.fetch;

  window.fetch = async function(input, init) {
    const response = await _fetch(input, init);

    try {
      const url      = input instanceof Request ? input.url : String(input);
      const hostname = new URL(url).hostname;
      const platform = PLATFORM_MAP[hostname];

      if (platform && isAiEndpoint(url) && response.body) {
        const cloned = response.clone();
        platform.parser(cloned, platform.name).catch(() => {});
      }
    } catch (_) {}

    return response;
  };

  console.log('[Mnemostroma] AI Interceptor loaded');
})();
