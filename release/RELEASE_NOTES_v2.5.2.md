# Release Notes — Mnemostroma v2.5.2

## Memory Growth Fix & Audit

v2.5.2 is a stability release focused on eliminating unbounded disk and memory growth. The primary fix adds periodic WAL checkpointing to LogWriter, preventing the WAL file from growing to 329 MB (12× the main DB). Backups were also rotated from 611 files (20 GB) down to 52 files (8.5 GB).

### Key Changes

- **WAL Checkpoint**: Periodic `PRAGMA wal_checkpoint(TRUNCATE)` every 5,000 writes in LogWriter flush loop. WAL reduced from 329 MB to ~3 MB and stays stable under load.
- **QueueFull Warning**: Silent drop of log entries replaced with `logger.warning` — no more invisible data loss.
- **ONNX Log Cleanup**: Automatic deletion of `onnx_logs` records older than 30 days (663K → 630K records, frees ~33K rows).
- **Backup Rotation**: Retained only 3 backups per month for April–June, selective for July. 611 files / 20 GB → 52 files / 8.5 GB.
- **Memory Audit**: Full analysis of RSS (stable at ~3.8 MB for daemon), WAL bloat root cause, ONNX model sizes, and per-directory space distribution.
- **SessionBrief Weight Measurement**: Direct `tracemalloc` measurement confirms ~0.4 KB per SessionBrief instance (~3–4 KB with embedding).

### Files Changed

| File | Change |
|------|--------|
| `storage/log_writer.py` | Periodic WAL checkpoint (`_flush_count`), QueueFull warning |
| `docs/audit/2026-07-28_memory_audit.md` | Full memory audit report |
| `docs/audit/session_weight_measurement.md` | Direct RAM measurement of SessionBrief |
| `docs/audit/memory_breakdown.md` | Memory usage analysis |
| `docs/audit/report_config-json.md` | Config audit findings |

### Upgrade Notes

No configuration changes needed. WAL checkpoint runs automatically every ~5,000 log writes (a few minutes under normal load). Existing WAL files are checkpointed on first flush cycle after upgrade.
