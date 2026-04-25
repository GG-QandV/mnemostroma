#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install-daemon.sh (universal) — Detect OS and launch appropriate setup
# Usage: bash scripts/install-daemon.sh
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# ─────────────────────────────────────────────────────────────────────
# 0. Verify Python 3.12+ is available
# ─────────────────────────────────────────────────────────────────────
PYTHON_BIN=""
for candidate in python3.12 python3.13 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,12))" 2>/dev/null || echo False)
        if [ "$ver" = "True" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3.12+ is required but not found on this system."
    echo "   Install it via: sudo apt install python3.12 python3.12-venv"
    echo "   Or via deadsnakes PPA: sudo add-apt-repository ppa:deadsnakes/ppa"
    exit 1
fi

PYTHON_VER=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python $PYTHON_VER found at $(command -v $PYTHON_BIN)"

# ─────────────────────────────────────────────────────────────────────
# 1. Auto-install: create venv and install mnemostroma if not installed
# ─────────────────────────────────────────────────────────────────────
VENV_DIR="$HOME/.mnemostroma/venv"
MNEMO_REPO="mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"

if [ ! -f "$VENV_DIR/bin/python3" ]; then
    echo "Creating virtual environment at $VENV_DIR (Python $PYTHON_VER)..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
    echo "Installing mnemostroma from GitHub..."
    "$VENV_DIR/bin/pip" install --quiet "$MNEMO_REPO"
    echo "✅ mnemostroma installed."
else
    echo "Updating mnemostroma..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade "$MNEMO_REPO"
    echo "✅ mnemostroma updated."
fi


SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 2. Detect Operating System
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

# 3. Golden Standard: Install Shell Aliases and Guards
echo "Installing shell aliases and guards..."
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

if ! grep -q "mnemo-health" "$SHELL_RC"; then
    cat >> "$SHELL_RC" << 'EOF'

# Mnemostroma aliases
alias mnemo-health="bash ~/.local/share/mnemostroma/scripts/mnemo-health.sh"
alias mnemo-restart="systemctl --user restart mnemostroma-daemon.service && sleep 3 && mnemostroma status"
alias mnemo-logs="journalctl --user -u mnemostroma-daemon.service -f"
alias mnemo-stop="systemctl --user stop mnemostroma-daemon.service mnemostroma-proxy.service"

# Auto-check on terminal open (silent unless problem)
_mnemo_guard() {
    local count
    count=$(pgrep -c -f "python.*-m mnemostroma run" 2>/dev/null || echo 0)
    if [ "$count" -gt 4 ]; then
        echo "⚠️  Mnemostroma: $count processes (limit ≤4). Run: mnemo-health"
    fi
    if systemctl --user is-active mnemostroma.service &>/dev/null 2>&1; then
        echo "🔴 mnemostroma.service is ACTIVE — must be disabled! Run: mnemo-health"
    fi
}
_mnemo_guard
EOF
    echo "  Aliases and guards added to $SHELL_RC"
    echo "  Please restart your terminal or run: source $SHELL_RC"
else
    echo "  Aliases already exist in $SHELL_RC"
fi

echo "Installation finalized."
