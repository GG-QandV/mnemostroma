# Quick Start — Mnemostroma v2.5.2

## Memory Growth Fix

v2.5.2 fixes unbounded WAL growth and cleans up backup bloat. No new features — pure stability.

### What's new in v2.5.2

- **WAL Checkpoint**: LogWriter now runs `PRAGMA wal_checkpoint(TRUNCATE)` every 5K writes. Prevents WAL from growing beyond a few MB.
- **Backup Rotation**: 611 files / 20 GB → 52 files / 8.5 GB.
- **Audit Reports**: Full memory growth analysis and SessionBrief RAM weight measurement in `docs/audit/`.

### Upgrade

```bash
cd /home/gg/projects/mnemostroma-public
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
