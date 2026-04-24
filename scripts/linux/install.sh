#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install_systemd.sh — Mnemostroma systemd user-unit installer
# Usage: bash install_systemd.sh [username]
# Default: current user
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

TARGET_USER=${1:-$(whoami)}
UNIT_DIR="/home/${TARGET_USER}/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing systemd units for user: ${TARGET_USER}"
echo "Unit dir: ${UNIT_DIR}"

# 1. Ensure unit directory exists
mkdir -p "${UNIT_DIR}"

# 2. Detect Python Environment
detect_python_bin() {
    # Option 1: pipx venv
    PIPX_PYTHON="/home/${TARGET_USER}/.local/pipx/venvs/mnemostroma/bin/python3"
    if [ -f "$PIPX_PYTHON" ]; then
        echo "$PIPX_PYTHON"
        return
    fi

    # Option 2: manual venv in ~/.mnemostroma
    VENV_PYTHON="/home/${TARGET_USER}/.mnemostroma/venv/bin/python3"
    if [ -f "$VENV_PYTHON" ]; then
        echo "$VENV_PYTHON"
        return
    fi

    # Option 3: Current environment (if running in venv)
    CURR_PYTHON=$(which python3)
    if [[ "$CURR_PYTHON" == *"/venv/"* || "$CURR_PYTHON" == *"/virtualenvs/"* ]]; then
        echo "$CURR_PYTHON"
        return
    fi

    # Fallback to system python (might fail on PEP 668)
    echo "/usr/bin/python3"
}

PYTHON_BIN=$(detect_python_bin)
VENV_BIN=$(dirname "$PYTHON_BIN")

echo "Using Python: ${PYTHON_BIN}"
echo "VENV_BIN: ${VENV_BIN}"

# 3. Deploy .service files with path substitution
for svc in mnemostroma-daemon mnemostroma-proxy mnemostroma-watchdog mnemostroma-ui; do
    sed \
        -e "s|%i|${TARGET_USER}|g" \
        -e "s|%h|/home/${TARGET_USER}|g" \
        -e "s|%VENV_BIN%|${VENV_BIN}|g" \
        -e "s|%MNEMOSTROMA_DIR%|/home/${TARGET_USER}/.mnemostroma|g" \
        "${SCRIPT_DIR}/${svc}.service" \
        > "${UNIT_DIR}/${svc}.service"
    echo "  Installed: ${UNIT_DIR}/${svc}.service"
done

# 3. Reload systemd if running as target user
if [ "$(whoami)" = "${TARGET_USER}" ]; then
    systemctl --user daemon-reload
    echo "  Reloaded user systemd"
else
    echo "  NOTE: manually run as ${TARGET_USER}: systemctl --user daemon-reload"
fi

# 4. Golden Standard: disable and cleanup deprecated units
if [ "$(whoami)" = "${TARGET_USER}" ]; then
    echo "Checking for duplicate/deprecated service units..."
    DEPRECATED_UNITS=("mnemostroma.service")

    for unit in "${DEPRECATED_UNITS[@]}"; do
        if systemctl --user is-enabled "$unit" &>/dev/null; then
            echo "  WARNING: Disabling deprecated unit: $unit"
            systemctl --user stop "$unit" 2>/dev/null || true
            systemctl --user disable "$unit" 2>/dev/null || true
        fi
    done

    # 5. Enable correct production units
    CORE_UNITS=(
        "mnemostroma-daemon.service"
        "mnemostroma-proxy.service"
        "mnemostroma-watchdog.service"
        "mnemostroma-ui.service"
    )

    for unit in "${CORE_UNITS[@]}"; do
        echo "  Enabling: $unit"
        systemctl --user enable "$unit"
    done
    
    echo "  All production units enabled."
fi

echo ""
echo "Management commands:"
echo "  systemctl --user start   mnemostroma-daemon"
echo "  mnemo-health (after terminal restart)"
echo "  journalctl --user -u mnemostroma-daemon -f"
echo ""
echo "Installation complete."
