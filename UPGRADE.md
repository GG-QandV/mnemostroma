# Mnemostroma Upgrade Guide

## Upgrading to v1.11.0 (Current)

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
