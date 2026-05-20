// SPDX-License-Identifier: FSL-1.1-MIT

/**
 * Mnemostroma Content Script for Perplexity.ai
 * Watches the DOM for messages and sends them to the local observer.
 */

let lastSentContent = "";
let debounceTimer = null;

function extractAllMessages() {
  // Perplexity uses different message structure
  // Try multiple selectors for robustness
  const messageNodes = document.querySelectorAll(
    '.message-content, [data-testid="message-content"], .px-4.py-3, .relative.group'
  );

  let transcript = [];
  messageNodes.forEach(node => {
    const text = node.innerText?.trim();
    if (text && text.length > 0) {
      // Simple heuristic: if text contains common user patterns, it's a user message
      const isUser = text.match(/^(user|me|you|i ):/i) ? true : false;
      const role = isUser ? 'user' : 'assistant';
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
  const sessionId = `perplexity-${today}`;

  chrome.runtime.sendMessage({
    type: "OBSERVE",
    data: {
      session_id: sessionId,
      text: content,
      source: "perplexity.ai"
    }
  });
}

// Observe DOM changes
const observer = new MutationObserver(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(notifyBackground, 1000);
});

observer.observe(document.body, { childList: true, subtree: true });

console.log("Mnemostroma: Content script active on Perplexity.ai");
