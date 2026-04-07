# Mnemostroma Alpha Testing Guide

---

## ALPHA TESTER AGREEMENT — READ BEFORE PROCEEDING

By installing or using this alpha build you confirm that you have read and agree to all
conditions below. If you do not agree, delete all received files immediately.

**1. Confidentiality.**
This build is confidential pre-release software. You must not disclose, describe, or
otherwise communicate the contents, features, architecture, or behavior of this software
to any third party without prior written permission from the project team.

**2. No redistribution.**
You must not copy, share, upload, publish, or otherwise distribute this build or any
part of it — in original or modified form — to any person, service, repository,
forum, or platform. This includes but is not limited to GitHub, GitLab, Hugging Face,
Discord, Telegram, Reddit, and any file-sharing or cloud storage services.

**3. No transfer of access.**
Your alpha access is personal and non-transferable. You must not provide this build,
your access credentials, or any derived artifacts to another person.

**4. Build identification.**
Each alpha build contains unique embedded identifiers. Any unauthorized distribution
can be traced to the specific build that was shared. Violation of this agreement will
result in immediate and permanent revocation of your alpha access.

**5. No reverse engineering.**
You must not decompile, disassemble, or attempt to extract proprietary model weights,
algorithms, or internal logic from this build beyond what is necessary for testing
and feedback purposes.

**6. Feedback ownership.**
Any feedback, bug reports, or suggestions you submit may be used by the project team
to improve the software without additional compensation or attribution.

**7. No warranty.**
This is pre-release software provided "as is" for testing purposes only. It may contain
bugs, incomplete features, or unexpected behavior. Do not use it in production
environments or with sensitive personal data.

---

## 1. Overview
Welcome to the Mnemostroma alpha build! This version includes extensive telemetry and logging tools to help us refine the system during these early stages. 

As an alpha tester, your primary goal is to use the system as usual while being aware of its internal state. If you encounter any anomalies, bugs, or unexpected behavior, the most valuable information you can provide is a snapshot of your system's logs. This data allows us to trace exactly what happened at each step—from memory acquisition to conflict detection.

## 2. Logging Modes
You can control the level of detail captured by the system in your `config.json` via the `logging.mode` parameter:

*   **"safe"** (Default): Captures only bootstrap, health checks, shutdown sequences, and all `ERROR` level events.
*   **"debug"**: Captures all system events, including every pipeline step and tool call. **Recommended for alpha testing.**

### Configuration Example
```json
{
  "logging": {
    "enabled": true,
    "mode": "debug",
    "db_path": "logs.db"
  }
}
```

## 3. Database Schema
Telemetry is stored in a SQLite database located at `~/.mnemostroma/logs.db`. The primary table is `onnx_logs`.

| Column | Type | Description |
| :--- | :--- | :--- |
| **id** | INTEGER | Auto-increment primary key |
| **ts** | INTEGER | Unix timestamp in milliseconds |
| **component** | TEXT | System component (e.g., `observer.pipe`) |
| **event** | TEXT | Event type (e.g., `classify`, `call`) |
| **data** | JSON | Event payload as a JSON string |
| **latency_ms** | REAL | Execution time in milliseconds |
| **session_id** | TEXT | Associated session ID (if applicable) |
| **level** | TEXT | `INFO` / `WARNING` / `ERROR` |

**Indexes:** `ts`, `component`, `session_id`.

## 4. Logged Components
The system currently tracks state across the following 23 components:

| Component | Event | What it captures |
| :--- | :--- | :--- |
| **conductor.bootstrap** | start | Daemon startup: `db_path`, `logs_path` |
| **conductor.health** | check | RAM usage (MB), observer alive status |
| **observer.pipe** | ner+embed | NER entity count, embedding dim, latency |
| **observer.marker** | classify | Anchor type, importance, session_type |
| **observer.score** | calculate | Score breakdown: relevance/temporal/importance |
| **observer.anchor** | create | Anchor id, type, key_facts count |
| **observer.save** | persist | Tags, layer (RAM_HOT), latency |
| **tuner.conflict** | check | Conflict detected (bool), flags, session_id |
| **tuner.conflict** | error | Exception message on conflict check failure |
| **tuner.drift** | check | Semantic drift score |
| **matrix.search** | query | Query vector dim, top_k, results count, latency |
| **reranker.rerank** | rerank | Candidates in/out, latency |
| **dissolver.evict** | evict | Evicted session_id, score, reason |
| **consolidation.recalc** | batch | Sessions checked, duration_ms |
| **anchor.decay** | batch | Anchors decayed, threshold_days |
| **storage.flush** | batch | Flushed_count, queue_depth |
| **dreamer.cycle** | complete | Dreamer stats (anchors reassessed) |
| **tools.semantic** | call | Query, results count, latency |
| **tools.search** | call | Tags, results count |
| **tools.anchors** | call | Anchor type filter, results count |
| **tools.active** | call | Active session snapshot size |
| **tools.admin** | various | sync/dump/load/growth/bridge operations |
| **feedback.implicit** | signal | Feedback signal type (USE/IGNORE/REVISIT) |
| **experience.signal** | fire | Intuition signal type, tag, maturity, avg_score |
| **calibration.update** | finalize | Old/new threshold, sample count |
| **tools.content_*** | call | Content branch tool calls |

## 5. CLI Commands
The Mnemostroma CLI provides tools for real-time monitoring and reporting:

```bash
# Live terminal dashboard (refresh every 2s)
mnemostroma watch --db ~/.mnemostroma/logs.db --interval 2

# Formatted log report (last 7 days)
mnemostroma logs --db ~/.mnemostroma/logs.db --days 7

# JSON output for scripting/reporting
mnemostroma logs --db ~/.mnemostroma/logs.db --json

# System tray indicator (macOS/Linux with display support)
mnemostroma tray --db ~/.mnemostroma/logs.db
```

## 6. SQL Queries
You can open `~/.mnemostroma/logs.db` with any SQLite client (DB Browser for SQLite, DBeaver, or the `sqlite3` CLI tool).

### Useful Queries:

**All events in the last hour:**
```sql
SELECT ts, component, event, latency_ms, data 
FROM onnx_logs 
WHERE ts > (strftime('%s','now') - 3600) * 1000 
ORDER BY ts DESC;
```

**All ERROR events:**
```sql
SELECT ts, component, event, data 
FROM onnx_logs 
WHERE level = 'ERROR' 
ORDER BY ts DESC;
```

**Average latency per component:**
```sql
SELECT component, event, 
       round(avg(latency_ms), 2) as avg_ms, 
       round(max(latency_ms), 2) as max_ms, 
       count(*) as calls 
FROM onnx_logs 
GROUP BY component, event 
ORDER BY avg_ms DESC;
```

**All events for a specific session:**
```sql
SELECT ts, component, event, data 
FROM onnx_logs 
WHERE session_id = '<your-session-id>' 
ORDER BY ts;
```

**Conflict detections only:**
```sql
SELECT ts, data, session_id 
FROM onnx_logs 
WHERE component = 'tuner.conflict' AND event = 'check' 
  AND json_extract(data, '$.detected') = 1;
```

**Slow operations (>100ms):**
```sql
SELECT ts, component, event, latency_ms, session_id 
FROM onnx_logs 
WHERE latency_ms > 100 
ORDER BY latency_ms DESC 
LIMIT 50;
```

**Observer pipeline throughput (events per minute):**
```sql
SELECT strftime('%H:%M', ts/1000, 'unixepoch') as minute, 
       count(*) as events 
FROM onnx_logs 
WHERE component LIKE 'observer.%' 
GROUP BY minute 
ORDER BY minute DESC 
LIMIT 30;
```

**Memory flush batches (tracking disk pressure):**
```sql
SELECT ts, json_extract(data, '$.flushed_count') as flushed, 
       json_extract(data, '$.queue_depth') as queue_depth 
FROM onnx_logs 
WHERE component = 'storage.flush' 
ORDER BY ts DESC LIMIT 20;
```

**Intuition signals fired (experience layer):**
```sql
SELECT ts, json_extract(data, '$.type') as type, 
       json_extract(data, '$.tag') as tag, 
       json_extract(data, '$.maturity') as maturity 
FROM onnx_logs 
WHERE component = 'experience.signal' 
ORDER BY ts DESC;
```

## 7. What to Report
When submitting a bug report or feedback, please include the relevant logs for:
*   Any events with `level = 'ERROR'`.
*   High latency: `latency_ms` > 500ms on `observer` or `search` components.
*   Unexpected conflict detections: `tuner.conflict` with `detected = 1`—please describe the session context.
*   Any behavior that differs from the expected system state.
