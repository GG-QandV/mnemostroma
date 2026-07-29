# System Assessment — Mnemostroma v2.5.3

**Date:** 2026-07-29

## Health Summary

| Indicator | Status | Notes |
|-----------|--------|-------|
| RSS (daemon) | ✅ ~435 MB | Post-NER-fix baseline, no growth trend |
| OOM kills | ✅ 0 | MemoryMax raised to 1000M |
| BertNER instances | ✅ 1/PID | Idempotent load + lock |
| Feedback signals | ✅ 19 valid, 0 None | signal→type fix |
| Scores | 🟡 still flat | retention_score added, needs burn-in |
| cgroup memory.peak | 696 MB | After cold start, within 850M High limit |
| WAL (logs.db) | ✅ ~10 MB | Normal for 630K records |
| Backups | ✅ 8.5 GB (52 files) | Down from 20 GB (611 files) |
| ONNX Logs | ✅ 630K records | 30-day retention enforced |

## Database

| DB | Size | Records | WAL |
|----|------|---------|-----|
| `mnemostroma.db` | 27 MB | 3,806 sessions | ~3 MB (checkpointed) |
| `logs.db` | 96 MB | 630K onnx_logs | ~10 MB |

## Memory (RSS)

| Process | RSS |
|---------|-----|
| `mnemostroma run` (core) | ~280 MB |
| `tray_pyqt` | ~32 MB |
| `http_proxy` | ~15 MB |
| `watchdog` | ~14 MB |
| `mcp_oauth_adapter` | ~12 MB |
| `tunnel` | ~11 MB |
| **Total (mnemo processes)** | **~400 MB** |

## Known Issues

- Whisper speech model not downloaded — `scripts/download_model.sh` pending
- `logs.db` VACUUM deferred (DB locked while daemon runs)
- `session_weight_measurement.md` confirms SessionBrief RAM weight ~0.4 KB base — embeddings dominate at ~1.5 KB each
