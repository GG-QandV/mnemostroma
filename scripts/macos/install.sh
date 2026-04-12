#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install.sh — установка launchd агента мнемостромы на macOS
# Использование: bash scripts/macos/install.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLIST_FILE="${SCRIPT_DIR}/com.mnemostroma.daemon.plist"
AGENT_DIR="${HOME}/Library/LaunchAgents"
AGENT_FILE="${AGENT_DIR}/com.mnemostroma.daemon.plist"

# Определить venv
VENV_BIN="${HOME}/.mnemostroma/venv/bin"
if [ ! -f "${VENV_BIN}/python3" ]; then
    echo "Error: Virtual env not found at ${VENV_BIN}/python3"
    echo "Run: python3 -m venv ${HOME}/.mnemostroma/venv"
    exit 1
fi

echo "Installing Mnemostroma daemon on macOS..."
echo "  VENV: ${VENV_BIN}"
echo "  HOME: ${HOME}"

# Создать LaunchAgents директорию
mkdir -p "${AGENT_DIR}"

# Копировать и подставить пути
sed \
    -e "s|%VENV_BIN%|${VENV_BIN}|g" \
    -e "s|%HOME%|${HOME}|g" \
    "${PLIST_FILE}" \
    > "${AGENT_FILE}"

echo "  ✓ Installed: ${AGENT_FILE}"

# Загрузить агент
launchctl load "${AGENT_FILE}"
echo "  ✓ Agent loaded"

# Запустить
launchctl start com.mnemostroma.daemon
echo "  ✓ Daemon started"

echo ""
echo "Management:"
echo "  launchctl start com.mnemostroma.daemon"
echo "  launchctl stop com.mnemostroma.daemon"
echo "  launchctl unload ~/Library/LaunchAgents/com.mnemostroma.daemon.plist"
echo ""
echo "Logs:"
echo "  tail -f ~/.mnemostroma/daemon.log"
echo "  tail -f ~/.mnemostroma/daemon.err"
