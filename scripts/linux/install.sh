#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────
# install_systemd.sh — установка systemd user-юнитов мнемостромы
# Использование: bash install_systemd.sh [username]
# Если username не передан — берёт текущего пользователя
# ─────────────────────────────────────────────────────────────────────
set -euo pipefail

TARGET_USER=${1:-$(whoami)}
UNIT_DIR="/home/${TARGET_USER}/.config/systemd/user"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Installing systemd units for user: ${TARGET_USER}"
echo "Unit dir: ${UNIT_DIR}"

# 1. Создать директорию для юнитов
mkdir -p "${UNIT_DIR}"

# 2. Скопировать .service файлы и подставить реальный username
for svc in mnemostroma-daemon mnemostroma-proxy mnemostroma-watchdog mnemostroma-ui; do
    sed \
        -e "s|%i|${TARGET_USER}|g" \
        -e "s|%h|/home/${TARGET_USER}|g" \
        -e "s|%VENV_BIN%|/home/${TARGET_USER}/.mnemostroma/venv/bin|g" \
        -e "s|%MNEMOSTROMA_DIR%|/home/${TARGET_USER}/.mnemostroma|g" \
        "${SCRIPT_DIR}/${svc}.service" \
        > "${UNIT_DIR}/${svc}.service"
    echo "  Installed: ${UNIT_DIR}/${svc}.service"
done

# 3. Перечитать юниты
if [ "$(whoami)" = "${TARGET_USER}" ]; then
    systemctl --user daemon-reload
    echo "  Reloaded user systemd"
else
    echo "  NOTE: run as ${TARGET_USER}: systemctl --user daemon-reload"
fi

# 4. Включить автозапуск
if [ "$(whoami)" = "${TARGET_USER}" ]; then
    systemctl --user enable mnemostroma-daemon
    systemctl --user enable mnemostroma-proxy
    systemctl --user enable mnemostroma-watchdog
    systemctl --user enable mnemostroma-ui
    echo "  Enabled all units"
fi

echo ""
echo "Управление:"
echo "  systemctl --user start   mnemostroma-daemon"
echo "  systemctl --user start   mnemostroma-proxy"
echo "  systemctl --user start   mnemostroma-watchdog"
echo "  journalctl --user -u mnemostroma-daemon -f"
echo ""
echo "Проверка статуса:"
echo "  systemctl --user status mnemostroma-daemon mnemostroma-proxy mnemostroma-watchdog"
