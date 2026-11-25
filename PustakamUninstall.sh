#!/usr/bin/env bash
# =====================================================================
#  Pustakam (पुस्तकम्) uninstaller for Linux (Debian & Red Hat families)
#  Removes the program, service, timer, cron entries and launcher.
#  Your notes in ~/.pustakam are kept unless you choose to delete them.
# =====================================================================
set -euo pipefail

APP="pustakam"
PORT=5150
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pustakam"
DATA_DIR="$HOME/.pustakam"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/pustakam.desktop"
SUDO=""; [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1 && SUDO="sudo"

echo "=================================================="
echo "   📖  Pustakam (पुस्तकम्) uninstaller"
echo "=================================================="

if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
    echo "🛑 Stopping services..."
    systemctl --user disable --now "${APP}.service" "${APP}-backup.timer" 2>/dev/null || true
    rm -f "$UNIT_DIR/${APP}.service" "$UNIT_DIR/${APP}-backup.service" "$UNIT_DIR/${APP}-backup.timer"
    systemctl --user daemon-reload
    systemctl --user reset-failed 2>/dev/null || true
fi

pkill -f "$INSTALL_DIR/app/PustakamApp.py" 2>/dev/null || true

if command -v crontab >/dev/null 2>&1; then
    CURRENT="$(crontab -l 2>/dev/null || true)"
    NEW="$(printf '%s\n' "$CURRENT" | grep -v '# Pustakam' || true)"
    if [[ "$CURRENT" != "$NEW" ]]; then printf '%s\n' "$NEW" | crontab -; echo "⏰ Cron entries removed"; fi
fi

if command -v firewall-cmd >/dev/null 2>&1 && $SUDO firewall-cmd --query-port=${PORT}/tcp >/dev/null 2>&1; then
    read -r -p "Close port ${PORT}/tcp in firewalld? [y/N] " r || true
    [[ "${r:-n}" =~ ^[Yy] ]] && $SUDO firewall-cmd --permanent --remove-port=${PORT}/tcp && $SUDO firewall-cmd --reload
elif command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "${PORT}/tcp"; then
    read -r -p "Remove the ufw rule for port ${PORT}/tcp? [y/N] " r || true
    [[ "${r:-n}" =~ ^[Yy] ]] && $SUDO ufw delete allow ${PORT}/tcp
fi

echo "📦 Removing program files..."
rm -f "$DESKTOP_FILE"
rm -rf "$INSTALL_DIR"

echo ""
echo "⚠️  Your notes, settings and backups are in: $DATA_DIR"
read -r -p "Delete them too? This cannot be undone. Type DELETE to confirm, or press Enter to keep: " r || true
if [[ "${r:-}" == "DELETE" ]]; then
    rm -rf "$DATA_DIR"
    echo "🗑️  Removed $DATA_DIR"
else
    echo "✅ Kept $DATA_DIR"
fi
echo ""
echo "✅ Pustakam has been uninstalled."
