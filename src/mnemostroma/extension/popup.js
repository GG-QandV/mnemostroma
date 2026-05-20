"use strict";

const OBSERVE_URL = "http://127.0.0.1:8766/observe";
const STORAGE_QUEUE_KEY = "mnemo_queue";

async function refresh() {
  // Check daemon health
  let daemonOk = false;
  try {
    const r = await fetch("http://127.0.0.1:8766/health", { signal: AbortSignal.timeout(1500) });
    daemonOk = r.ok;
  } catch (_) { }

  document.getElementById("daemon-status").textContent = daemonOk ? "● up" : "● down";
  document.getElementById("daemon-status").className = daemonOk ? "ok" : "err";

  // MCP URL
  try {
    const cfg = await fetch("http://127.0.0.1:8766/mcp-config", { signal: AbortSignal.timeout(1500) })
      .then(r => r.json());
    const url = cfg.public_url ?? cfg.local_url ?? "";
    document.getElementById("mcp-url").value = url;
    document.getElementById("copy-btn").onclick = () => navigator.clipboard.writeText(url);
  } catch (_) {
    document.getElementById("mcp-url").value = "daemon not running";
  }

  // Queue size
  const data = await chrome.storage.local.get(STORAGE_QUEUE_KEY);
  const q = data[STORAGE_QUEUE_KEY] ?? [];
  document.getElementById("queue-size").textContent = q.length;
}

document.getElementById("retry-btn").addEventListener("click", async () => {
  chrome.alarms.create("mnemo-retry", { delayInMinutes: 0 });
  setTimeout(refresh, 800);
});

refresh();
