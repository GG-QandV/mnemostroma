#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install-daemon.sh (universal) v1.8.5.1
# Usage: bash scripts/install-daemon.sh [--local]
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

# 0. Detect Mode
INSTALL_MODE="github"
if [[ "${1:-}" == "--local" ]]; then
    INSTALL_MODE="local"
    echo "⚡ Local editable mode enabled."
fi

# 1. Verify Python 3.12+
PYTHON_BIN=""
for candidate in python3.12 python3.13 python3 python; do
    if command -v "$candidate" &>/dev/null; then
        ver=$("$candidate" -c "import sys; print(sys.version_info >= (3,12))" 2>/dev/null || echo False)
        if [ "$ver" = "True" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Python 3.12+ required."
    exit 1
fi

PYTHON_VER=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "✅ Python $PYTHON_VER found."

# 2. Setup VENV
VENV_DIR="$HOME/.mnemostroma/venv"
mkdir -p "$HOME/.mnemostroma"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

if [ ! -f "$VENV_DIR/bin/python3" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if [ "$INSTALL_MODE" == "local" ]; then
    echo "Installing from local source..."
    "$VENV_DIR/bin/pip" install -e "$REPO_ROOT[all]"
else
    echo "Installing from GitHub..."
    "$VENV_DIR/bin/pip" install --quiet --upgrade "mnemostroma[all] @ git+https://github.com/GG-QandV/mnemostroma.git"
fi

# 2.5 Download models
echo "Downloading models..."
"$VENV_DIR/bin/mnemostroma" download-models

# 3. Clean Zombies
echo "Ensuring clean state..."
if [ -f "$SCRIPT_DIR/../scripts/clean-zombies.py" ]; then
    "$VENV_DIR/bin/python" "$SCRIPT_DIR/../scripts/clean-zombies.py" || echo "Warning: clean-zombies failed"
else
    # Fallback to module command if installed
    "$VENV_DIR/bin/mnemostroma" cleanup --silent || true
fi

# 4. Detect OS and run specific installer
OS_TYPE=$(uname -s)
case "${OS_TYPE}" in
    Linux) bash "${SCRIPT_DIR}/linux/install.sh" "$@" ;;
    Darwin) bash "${SCRIPT_DIR}/macos/install.sh" "$@" ;;
    *) echo "Error: Unsupported OS: ${OS_TYPE}"; exit 1 ;;
esac

# 5. Smart Aliases/Guards
SHELL_RC="$HOME/.bashrc"
[ -f "$HOME/.zshrc" ] && SHELL_RC="$HOME/.zshrc"

GUARD_BLOCK_START="# MNEMOSTROMA_START"
GUARD_BLOCK_END="# MNEMOSTROMA_END"

# Remove old block
if grep -q "$GUARD_BLOCK_START" "$SHELL_RC"; then
    sed -i "/$GUARD_BLOCK_START/,/$GUARD_BLOCK_END/d" "$SHELL_RC"
fi

# Add new block
cat >> "$SHELL_RC" << EOF

$GUARD_BLOCK_START
alias mnemo-health="$SCRIPT_DIR/mnemo-health.sh"
alias mnemo-restart="systemctl --user restart mnemostroma-daemon.service mnemostroma-proxy.service mnemostroma-watchdog.service && sleep 3 && mnemostroma status"
alias mnemo-logs="journalctl --user -u mnemostroma-daemon.service -f"
$GUARD_BLOCK_END
EOF

echo "Installation finalized."
