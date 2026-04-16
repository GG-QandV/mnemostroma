// SPDX-License-Identifier: FSL-1.1-MIT

/**
 * Mnemostroma Background Script
 * Relays messages from the content script to the local Mnemostroma adapter.
 */

const OBSERVE_URL = "http://localhost:8766/observe";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === "OBSERVE") {
    console.log("Mnemostroma: Relaying message to local observer...", message.data.session_id);
    
    fetch(OBSERVE_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: json_stringify(message.data)
    })
    .then(response => {
      if (!response.ok) {
        console.error("Mnemostroma: Failed to send to observer", response.statusText);
      }
    })
    .catch(error => {
      console.error("Mnemostroma: Connection to observer failed. Is the adapter running?", error);
    });
  }
});

// Helper to avoid issues with JSON.stringify in some environments
function json_stringify(obj) {
  return JSON.stringify(obj);
}

console.log("Mnemostroma: Background service worker active");
