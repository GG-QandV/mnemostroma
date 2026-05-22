## Upgrading to v2.3.0 Beta (Current)

### What changed
- `mnemostroma tunnel` now uses **Cloudflare Tunnel** instead of Serveo SSH.
  Serveo support is removed.
- A new `mnemostroma-tunnel.service` systemd unit replaces `mnemostroma-serveo.service`.
- New port **8769** for the MCP OAuth Adapter (does not conflict with existing ports).

### Migration steps

**If you used Serveo (`mnemostroma-serveo.service`):**
```bash
# Stop and disable the old unit
systemctl --user stop mnemostroma-serveo
systemctl --user disable mnemostroma-serveo

# Install the new tunnel unit
mnemostroma service install --component tunnel

# Start
mnemostroma tunnel start
```

**If you didn't use Serveo** — no action needed. Run `bash scripts/update.sh` as usual.

---

## Upgrading to v2.2.7

No breaking changes. The browser extension is automatically updated to v1.0.5
during `mnemostroma setup` or via `mnemostroma install-extension`.

**New in extension v1.0.5:**
- Grok (xAI / grok.com) adapter added
- ES modules architecture (replaces legacy bundle)
- Improved badge health check

If your extension was loaded from `~/.mnemostroma/extension/` (Simple Path),
run:
```bash
mnemostroma install-extension
# then reload the extension in your browser
```

---

## Upgrading to v1.11.1 (Previous)

This is a **stability patch** for the installer pipeline. No schema migrations required.

### Steps to Upgrade

**From v1.11.0 via GitHub:**
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/GG-QandV/mnemostroma/main/scripts/install-daemon.sh)
```

**From local clone:**
```bash
git pull origin main
~/.mnemostroma/venv/bin/pip install --upgrade "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
mnemostroma off && mnemostroma on
```

**What changed:**
- Installer no longer crashes with `FileNotFoundError: models_manifest.json` on fresh installs
- `bash <(curl ...)` mode no longer fails with `/dev/fd/linux/install.sh: No such file or directory`
- Editable dev installs are now preserved across `install-daemon.sh` re-runs

No configuration changes. No DB migration needed.

### Do I need to run `mnemostroma service install`?

| Situation | Required? |
|---|---|
| Your v1.11.0 daemon was working normally | ❌ Not required |
| Your install failed with `/dev/fd/linux/install.sh: No such file or directory` | ✅ Required — your unit files were never written |
| Fresh install on a new machine | ✅ Called automatically by the installer |
| You want to refresh unit files to latest templates | ✅ Optional but safe (idempotent) |

`mnemostroma service install` is always safe to run — it is fully idempotent and will not affect your data or configuration.

---
# Mnemostroma Upgrade Guide

## Upgrading to v1.11.0

This version introduces **Content Branch automation** (Mechanism #12) and **Exact Time search** capabilities.

### Steps to Upgrade

1. **Update code:**
   ```bash
   git pull origin main
   ```
2. **Restart services:**
   ```bash
   mnemostroma off
   mnemostroma on
   ```

## Upgrading to v1.8.5 (Recommended)

This version is a critical stability release that unifies the single-daemon architecture and stabilizes service management.

### Steps to Upgrade

1. **Stop existing services:**
   ```bash
   mnemostroma off
   ```
2. **Clean up lingering processes:**
   ```bash
   python3 scripts/clean-zombies.py
   ```
3. **Update code and dependencies:**
   ```bash
   git pull origin main
   pip install -e ".[all]"
   ```
4. **Re-install systemd services:**
   ```bash
   mnemostroma service install
   ```
5. **Start:**
   ```bash
   mnemostroma on
   ```

### Major Changes Since v1.8.0

- **Hexagonal Architecture**: If you use custom adapters, note that the storage layer is now strictly decoupled via Ports.
- **Service Management**: `mnemostroma service install` is now the universal command for Linux, macOS, and Windows.
- **RAM Baseline**: Baseline RSS is ~420MB. Ensure your machine has at least 1GB available for peak usage.

---
[Back to README.md](./README.md)
