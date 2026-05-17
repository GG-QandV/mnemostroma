#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install.sh — установка launchd агента мнемостромы на macOS
# Использование: bash scripts/macos/install.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

INSTALL_MODE="github"
if [[ "${1:-}" == "--local" ]]; then
    INSTALL_MODE="local"
    echo "⚡ Local editable mode enabled."
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
AGENT_DIR="${HOME}/Library/LaunchAgents"

VENV_DIR="${HOME}/.mnemostroma/venv"
VENV_BIN="${VENV_DIR}/bin"

echo "Installing Mnemostroma on macOS..."

# 1. Setup VENV and Install
if [ ! -f "${VENV_BIN}/python3" ]; then
    echo "  Creating virtual environment..."
    PYTHON_CMD="python3"
    if ! command -v $PYTHON_CMD &>/dev/null; then PYTHON_CMD="python"; fi
    $PYTHON_CMD -m venv "${VENV_DIR}"
fi

if [ "$INSTALL_MODE" == "local" ]; then
    echo "  Installing from local source..."
    "${VENV_BIN}/pip" install -e "${REPO_ROOT}[all]"
else
    echo "  Installing from GitHub..."
    "${VENV_BIN}/pip" install --quiet --upgrade "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
fi

# 2. Download Models
echo "  Downloading models..."
"${VENV_BIN}/mnemostroma" download-models

# 3. Create LaunchAgents directory
mkdir -p "${AGENT_DIR}"

# 4. Copy and patch plists
SERVICES=("daemon" "proxy" "watchdog")
for svc in "${SERVICES[@]}"; do
    PLIST_SRC="${SCRIPT_DIR}/com.mnemostroma.${svc}.plist"
    PLIST_DEST="${AGENT_DIR}/com.mnemostroma.${svc}.plist"
    
    if [ -f "$PLIST_SRC" ]; then
        sed \
            -e "s|%VENV_BIN%|${VENV_BIN}|g" \
            -e "s|%HOME%|${HOME}|g" \
            "${PLIST_SRC}" \
            > "${PLIST_DEST}"
        echo "  ✓ Installed: ${PLIST_DEST}"
    fi
done

# 5. Load agents (using modern bootstrap)
UID=$(id -u)
for svc in "${SERVICES[@]}"; do
    PLIST_DEST="${AGENT_DIR}/com.mnemostroma.${svc}.plist"
    if [ -f "$PLIST_DEST" ]; then
        # Unload if exists
        launchctl bootout "gui/${UID}" "${PLIST_DEST}" 2>/dev/null || true
        # Load
        launchctl bootstrap "gui/${UID}" "${PLIST_DEST}"
        echo "  ✓ Service com.mnemostroma.${svc} loaded"
    fi
done

echo ""
echo "Management:"
echo "  Start/Stop (e.g. daemon): launchctl start com.mnemostroma.daemon"
echo ""
echo "Logs:"
echo "  tail -f ~/.mnemostroma/daemon.log"
echo "  tail -f ~/.mnemostroma/proxy.log"
echo "  tail -f ~/.mnemostroma/watchdog.log"
echo ""
echo "📢 IMPORTANT NEXT STEP:"
echo "To capture chat sessions from Claude, Perplexity, ChatGPT, Gemini, etc. into Mnemostroma,"
echo "you MUST load the Mnemostroma browser extension into your browser."
echo "Read the easy setup guide:"
echo "👉 src/extension/docs/INSTALL.md"
echo ""
