// SPDX-License-Identifier: FSL-1.1-MIT

/**
 * Mnemostroma Content Script for Grok (X/xAI)
 * Watches the DOM for messages and sends them to the local observer.
 */

let lastSentContent = "";
let debounceTimer = null;

function extractAllMessages() {
  // Grok/X AI message structure - try multiple selectors
  const messageNodes = document.querySelectorAll(
    '[data-testid="message"], .message, .chat-message, [role="article"], .rounded-lg.border'
  );

  let transcript = [];
  messageNodes.forEach(node => {
    const isUser = node.className?.includes('user') ||
                   node.getAttribute('data-testid')?.includes('user') ||
                   node.innerText?.startsWith('You:');
    const role = isUser ? 'user' : 'assistant';
    const text = node.innerText?.trim();
    if (text && text.length > 0) {
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
  const sessionId = `grok-${today}`;

  chrome.runtime.sendMessage({
    type: "OBSERVE",
    data: {
      session_id: sessionId,
      text: content,
      source: "grok.x.com"
    }
  });
}

// Observe DOM changes
const observer = new MutationObserver(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(notifyBackground, 1000);
});

observer.observe(document.body, { childList: true, subtree: true });

console.log("Mnemostroma: Content script active on Grok");
