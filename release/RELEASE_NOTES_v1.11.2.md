# Release Notes — Mnemostroma v1.11.2

## 🔧 Core Stability Hotfix

This is a targeted hotfix release. No new features. No breaking changes. No DB migration required.

The patch fixes a critical regression introduced in v1.11.1: a missing import in `conductor.py`
that caused the daemon to crash on every startup after a fresh install from GitHub.

---

### Fixed Issues

- **`NameError: name 'LogWriter' is not defined`** — `conductor.py`  
  The `LogWriter` class was relocated to `mnemostroma.storage.log_writer` during the v1.11.0
  refactor, but the corresponding import was not added to `conductor.py`. This caused an
  immediate `NameError` crash on daemon startup for any installation that pulled the source
  from GitHub (pip, curl-pipe, or manual clone).  
  Discovered during a live v1.11.1 field upgrade on Linux.  
  **Fix:** Added `from mnemostroma.storage.log_writer import LogWriter` to `conductor.py`.

---

### New in v1.11.2

- **`scripts/update_version.py`** — Automated version management script.  
  Single source of truth: reads version from `pyproject.toml`, updates README badge,
  UPGRADE header, `**Current:**` status line, and `version.py` CLI banner in one run.
  Includes stale-reference scan and `previous_version` rotation in `[tool.mnemostroma]`.

---

### What Did NOT Change

- No new features
- No API changes
- No DB schema changes
- No configuration format changes
- No installer changes
- Test suite: 502 passed (no regressions)

---

### Upgrade Instructions

See [UPGRADE.md](../UPGRADE.md) → *Upgrading to v1.11.2*

---

**Generated:** 2026-05-10  
**Mnemostroma:** The memory layer for AI agents  
**v1.11.2** | 502 tests passing | 0 regressions | Core stability hotfix
