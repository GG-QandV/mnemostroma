# Quick Start — Mnemostroma v2.5.3

## Relevance + Memory Quality Release

v2.5.3 restores relevance scoring, hardens NER lifecycle, and fixes memory scoring correctness.

### What's new in v2.5.3

- **Relevance**: `intent_vector` now flows from search to observer pipeline — relevance = `dot(session_embedding, query_embedding)` instead of always 0.5.
- **NER**: BertNER.load() idempotent with lock — no more duplicate ONNX sessions (~575/day → 1).
- **Scoring**: Removed R=0.5 overwrite from consolidation; added `calculate_retention_score()` for eviction.
- **Infra**: Systemd MemoryMax 1000M, OOM-kills eliminated, cgroup observability.

### Upgrade

```bash
cd /home/gg/projects/Project_mnemostroma
git pull origin main
pip install -e ".[dev]"
```

No config changes needed. Restart the daemon to pick up the new LogWriter:

```bash
systemctl --user restart mnemostroma-daemon
```

### Verify

```bash
# 1. Check WAL size after a few minutes of runtime
ls -lh ~/.mnemostroma/mnemostroma.db-wal
# Expected: ~3 MB (not 300+)

# 2. Check backup count
ls ~/.mnemostroma/backups/ | wc -l
# Expected: 52

# 3. Daemon RSS
ps aux | grep "[m]nemostroma run" | awk '{print $6 " KB"}'
# Expected: ~270-300 MB
```
