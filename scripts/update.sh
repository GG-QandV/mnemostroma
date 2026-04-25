#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# Mnemostroma — Aggressive Auto-Update Script (v2.0)
# ─────────────────────────────────────────────────────────────────────
set -uo pipefail # Не используем -e, чтобы обработать ошибки остановки вручную

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_BIN="$HOME/.mnemostroma/venv/bin"
PYTHON_BIN="$VENV_BIN/python3"
MNEMO_BIN="$VENV_BIN/mnemostroma"

echo "🧹 Phase 1: Aggressive Cleanup..."
# Останавливаем системные службы (независимо от их состояния)
systemctl --user stop mnemostroma-daemon mnemostroma-proxy mnemostroma-watchdog 2>/dev/null || true
# Запускаем скрипт очистки зомби
"$PYTHON_BIN" "$REPO_DIR/scripts/clean-zombies.py"

echo "📥 Phase 2: Syncing Code & Dependencies..."
if [ -d "$REPO_DIR/.git" ]; then
    git -C "$REPO_DIR" pull
fi

if command -v uv &> /dev/null; then
    uv sync --project "$REPO_DIR"
else
    "$VENV_BIN/pip" install -e "$REPO_DIR"
fi

echo "⚙️  Phase 3: Refreshing System Services..."
"$MNEMO_BIN" service install
systemctl --user daemon-reload

echo "🚀 Phase 4: Orderly Startup..."
# Запускаем полный стек через systemd
systemctl --user start mnemostroma-daemon mnemostroma-proxy mnemostroma-watchdog

# Ждем появления сокета (до 10 секунд)
echo "⌛ Waiting for daemon socket..."
for i in {1..10}; do
    if [ -S "$HOME/.mnemostroma/daemon.sock" ]; then
        echo "   ✓ Socket ready."
        break
    fi
    sleep 1
done

echo -e "\n✅ Update complete! Final Status:"
sleep 1
"$MNEMO_BIN" status

# Проверка прокси
echo "⌛ Waiting for proxy port 8767..."
for i in {1..5}; do
    if ss -tln | grep -q ":8767"; then
        echo "⚡ Proxy is UP on port 8767"
        break
    fi
    sleep 1
    if [ $i -eq 5 ]; then
        echo "❌ Proxy failed to start or port 8767 is blocked"
    fi
done
