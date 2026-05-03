# Release Notes — Mnemostroma v1.11.1

## 🔧 Installer Stability Patch

This is a targeted stability release focused entirely on the installation pipeline. No new features. No breaking changes. No DB migration required.

This patch was triggered by a user report confirming two reproducible failures on fresh curl-pipe installs.

### Fixed Issues

- **`FileNotFoundError: models_manifest.json`**  
  On fresh installs, the model downloader failed because `models_manifest.json` was not provisioned before being read. The new `_ensure_manifest()` function now atomically copies the bundled manifest to `~/.mnemostroma/` before any model operation runs.

- **`/dev/fd/linux/install.sh: No such file or directory`**  
  When installing via `bash <(curl ...)`, `$SCRIPT_DIR` resolves to `/dev/fd` (a pipe). The old code attempted to call `${SCRIPT_DIR}/linux/install.sh`, which fails. Service installation is now handled entirely by `mnemostroma service install` (Python-native, no shell path dependency).

- **Editable install preservation** (`R-09`)  
  Re-running `install-daemon.sh` on a developer machine with an editable install (`pip install -e .`) would silently overwrite it with a static GitHub copy. The installer now detects editable installs and skips the overwrite.

- **Silent `systemctl enable` failures** (`R-05`)  
  The `enable` loop now tracks per-unit exit codes and reports failures explicitly instead of printing `✓ 3 core units enabled` regardless of outcome.

- **Inconsistent service `WorkingDirectory`** (`R-06`)  
  `mnemostroma-sse.service` used a custom `%MNEMOSTROMA_DIR%` marker instead of the systemd-native `%h` specifier. All five unit files now use `%h/.mnemostroma` consistently.

- **Silent `service install` failure in shell script** (`R-02`)  
  `mnemostroma service install` in `install-daemon.sh` was not guarded. Failures would be ignored under `set -e`. Now wrapped with `|| { echo ...; exit 1; }`.

---

### What Did NOT Change

- No new features
- No API changes
- No DB schema changes
- No configuration format changes
- Test suite: 502 passed (up from 501 in v1.11.0, one new test covering manifest provisioning)

---

### Upgrade Instructions

See [UPGRADE.md](../UPGRADE.md) → *Upgrading to v1.11.1*

---

**Generated:** 2026-05-03  
**Mnemostroma:** The memory layer for AI agents  
**v1.11.1** | 502 tests passing | 0 regressions | Installer stability patch
