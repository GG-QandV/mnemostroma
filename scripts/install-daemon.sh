#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install-daemon.sh (universal) — определить ОС и запустить нужный setup
# Использование: bash scripts/install-daemon.sh
# ─────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Определить ОС
OS_TYPE=$(uname -s)

case "${OS_TYPE}" in
    Linux)
        echo "Detected: Linux (systemd)"
        bash "${SCRIPT_DIR}/linux/install.sh" "$@"
        ;;
    Darwin)
        echo "Detected: macOS (launchd)"
        bash "${SCRIPT_DIR}/macos/install.sh" "$@"
        ;;
    *)
        echo "Error: Unsupported OS: ${OS_TYPE}"
        echo ""
        echo "Windows users: run scripts/windows/install-daemon.ps1 in PowerShell"
        exit 1
        ;;
esac
