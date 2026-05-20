// SPDX-License-Identifier: FSL-1.1-MIT

/**
 * Mnemostroma Content Script for ChatGPT
 * Watches the DOM for messages and sends them to the local observer.
 */

let lastSentContent = "";
let debounceTimer = null;

function extractAllMessages() {
  // ChatGPT uses group/conversation-turn structure
  const messageNodes = document.querySelectorAll(
    '.group\\/conversation-turn, [data-testid="message"], .space-y-4 > div'
  );

  let transcript = [];
  messageNodes.forEach(node => {
    // Check if it's a user message (usually has different styling/data attributes)
    const isUser = node.className?.includes('user') ||
                   node.getAttribute('data-testid')?.includes('user') ||
                   node.innerText?.startsWith('You');
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
  const sessionId = `chatgpt-${today}`;

  chrome.runtime.sendMessage({
    type: "OBSERVE",
    data: {
      session_id: sessionId,
      text: content,
      source: "chatgpt.com"
    }
  });
}

// Observe DOM changes
const observer = new MutationObserver(() => {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(notifyBackground, 1000);
});

observer.observe(document.body, { childList: true, subtree: true });

console.log("Mnemostroma: Content script active on ChatGPT");
