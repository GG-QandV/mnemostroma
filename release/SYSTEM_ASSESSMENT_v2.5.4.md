# System Assessment — Mnemostroma v2.5.4

**Date:** 2026-09-18
**Source:** live snapshot of the running daemon at release time (local `main` @ cd137b2) + full test run.

## Health Summary

| Indicator | Status | Notes |
|-----------|--------|-------|
| HTTP Read adapter (8762) | ✅ ok | `/health` → `{"status":"ok","adapter":"http_read","daemon":"connected"}` |
| Daemon RAM | ✅ ~203 MB | `pulse.json` `ram_mb` = 203, `ram_pct` = 32.2 |
| RAM index | ✅ 200 sessions | `status.json` `ram_index_count` = 200, `session_index_count` = 200 |
| Content index | ✅ 4 blocks | `content_index_count` = 4 |
| Pending writes | ✅ 0 | `pending_writes` = 0 |
| Model footprint accounting | ✅ present | `models/footprint.py` wired into Dissolver baseline |
| Tests | ✅ 1729 passed, 52 skipped | full run, green |

## Database

| DB | Size | Notes |
|----|------|-------|
| `~/.mnemostroma/mnemostroma.db` | 80 MB | sessions/anchors/precision + WAL |
| `~/.mnemostroma/logs.db` | 192 MB | telemetry (30-day retention) |

## Memory (RSS, snapshot)

| Process | RSS |
|---------|-----|
| daemon (`mnemostroma run`, python3) | ~203 MB |
| other mnemostroma helpers (proxy/tray/watchdog/tunnel/adapter) | ~150 MB combined |
| **Total (rough)** | **~370 MB** |

The v2.5.4 change to `onnx_baseline_mb` means model weights are no longer counted as evictable:
session eviction is driven by the process baseline only, and per-model weight is tracked separately
via `models/footprint.py`.

## Known Issues / Deferred

- `logs.db` VACUUM deferred (DB locked while daemon runs).
- Whisper speech model not downloaded (`scripts/download_model.sh` pending) — speech-local track.
- Local venv still reports the previously installed version until `pip install -U` is run;
  the release source is v2.5.4.

## Verification commands

```bash
curl -s http://127.0.0.1:8762/health
curl -s http://127.0.0.1:8766/metrics | head
python3 -c "import json;print(json.load(open('$HOME/.mnemostroma/status.json')))"
```
