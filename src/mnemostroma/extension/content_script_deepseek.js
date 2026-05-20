// SPDX-License-Identifier: FSL-1.1-MIT

/**
 * Mnemostroma Content Script for DeepSeek
 * Watches the DOM for messages and sends them to the local observer.
 */

let lastSentContent = "";
let debounceTimer = null;

function extractAllMessages() {
  // DeepSeek similar to Claude, uses data-testid attributes
  const messageNodes = document.querySelectorAll(
    '[data-testid="user-message"], [data-testid="assistant-message"], .message, [role="article"]'
  );

  let transcript = [];
  messageNodes.forEach(node => {
    const isUser = node.getAttribute('data-testid') === 'user-message' ||
                   node.className?.includes('user');
    const role = isUser ? 'user' : 'assistant';
    const text = node.innerText?.trim();
    if (text) {
      transcript.push(`[${role}]: ${text}`);
    }
  });

  return transcript.join('\n\n');
}

function notifyBackground() {
  const content = extractAllMessages();
  if (!content || content === lastSentContent) return;

  lastSentContent = content;

  const today = new Date().toISOString().split('T')[0];
  const sessionId = `deepseek-${today}`;

  chrome.runtime.sendMessage({
    type: "OBSERVE",
    data: {
      session_id: sessionId,
      text: content,
      source: "deepseek.com"
    }
  });
}

// Observe DOM changes
const observer = new MutationObserver(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(notifyBackground, 1000);
});

observer.observe(document.body, { childList: true, subtree: true });

console.log("Mnemostroma: Content script active on DeepSeek");
