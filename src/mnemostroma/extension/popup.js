"use strict";

const OBSERVE_URL = "http://localhost:8766/observe";
const STORAGE_QUEUE_KEY = "mnemo_queue";

async function refresh() {
  // Check daemon health
  let daemonOk = false;
  try {
    const r = await fetch("http://localhost:8765/health", { signal: AbortSignal.timeout(1500) });
    daemonOk = r.ok;
  } catch (_) {}

  document.getElementById("daemon-status").textContent = daemonOk ? "● up" : "● down";
  document.getElementById("daemon-status").className = daemonOk ? "ok" : "err";

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
