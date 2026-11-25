#!/usr/bin/env bash
# =====================================================================
#  Pustakam (पुस्तकम्) installer for Linux
#  Debian family : Debian, Ubuntu, Mint, MX Linux, siduction, Pop!_OS ... (apt)
#  Red Hat family: Fedora, RHEL, Rocky, AlmaLinux, CentOS Stream ...    (dnf / yum)
#  Also works on openSUSE (zypper).
#
#  Installs for the CURRENT user (no root needed except to install missing
#  system packages). Runs as a systemd *user* service, so Pustakam signs you
#  in with this Linux account.
#
#  Usage:  ./PustakamInstall.sh            (interactive)
#          ./PustakamInstall.sh --yes      (accept all defaults)
# =====================================================================
set -euo pipefail

APP="pustakam"
PK_VERSION="1.1"
PORT=5150
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/pustakam"
APP_DIR="$INSTALL_DIR/app"
VENV_DIR="$INSTALL_DIR/venv"
DATA_DIR="$HOME/.pustakam"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
DESKTOP_FILE="${XDG_DATA_HOME:-$HOME/.local/share}/applications/pustakam.desktop"
ASSUME_YES=0
[[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && ASSUME_YES=1

c_ok()   { printf '\033[1;32m%s\033[0m\n' "$*"; }
c_info() { printf '\033[1;36m%s\033[0m\n' "$*"; }
c_warn() { printf '\033[1;33m%s\033[0m\n' "$*"; }
die()    { printf '\033[1;31m✖ %s\033[0m\n' "$*" >&2; exit 1; }
ask() {  # ask "question" default(y/n)
    local q="$1" def="${2:-n}" reply
    if [[ $ASSUME_YES -eq 1 ]]; then [[ "$def" == "y" ]]; return; fi
    local hint="[y/N]"; [[ "$def" == "y" ]] && hint="[Y/n]"
    read -r -p "$q $hint " reply || true
    reply="${reply:-$def}"
    [[ "$reply" =~ ^[Yy] ]]
}
SUDO=""
if [[ $EUID -ne 0 ]]; then command -v sudo >/dev/null 2>&1 && SUDO="sudo"; fi

echo "=================================================="
echo "   📖  Pustakam (पुस्तकम्) installer  v${PK_VERSION}"
echo "=================================================="

[[ $EUID -eq 0 ]] && c_warn "⚠ You are running as root. Pustakam will run as root and only 'root' can sign in. Run as your normal user instead unless you really want that."

# ------------------------------------------------------------- distro
OS_ID="unknown"; OS_LIKE=""
if [[ -r /etc/os-release ]]; then . /etc/os-release; OS_ID="${ID:-unknown}"; OS_LIKE="${ID_LIKE:-}"; fi
PKG=""
if   command -v apt-get >/dev/null 2>&1; then PKG="apt"
elif command -v dnf     >/dev/null 2>&1; then PKG="dnf"
elif command -v yum     >/dev/null 2>&1; then PKG="yum"
elif command -v zypper  >/dev/null 2>&1; then PKG="zypper"
fi
c_info "🐧 Detected: ${PRETTY_NAME:-$OS_ID} (package manager: ${PKG:-none})"

pkg_install() {
    [[ -z "$PKG" ]] && die "Please install these packages yourself: $*"
    [[ -z "$SUDO" && $EUID -ne 0 ]] && die "Need root to install: $* (install sudo or run those installs as root)"
    c_info "📦 Installing system packages: $*"
    case "$PKG" in
        apt)    $SUDO apt-get update -qq && $SUDO apt-get install -y "$@" ;;
        dnf)    $SUDO dnf install -y "$@" ;;
        yum)    $SUDO yum install -y "$@" ;;
        zypper) $SUDO zypper --non-interactive install "$@" ;;
    esac
}

# ------------------------------------------------------------- python >= 3.11
find_python() {
    for c in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>/dev/null; then
            echo "$c"; return 0
        fi
    done
    return 1
}
PY="$(find_python || true)"
if [[ -z "$PY" ]]; then
    c_warn "Python 3.11 or newer was not found (have: $(python3 --version 2>/dev/null || echo none))."
    # Step 1: the distro's default python3 (3.11+ on Debian 12+, Ubuntu 24.04+, Fedora, RHEL 10)
    case "$PKG" in
        apt)     NEED=(python3 python3-venv python3-pip) ;;
        dnf|yum) NEED=(python3 python3-pip) ;;
        zypper)  NEED=(python3 python3-pip) ;;
        *)       NEED=(python3) ;;
    esac
    # Step 2: a side-by-side 3.11 package (Ubuntu 22.04, RHEL/Rocky/Alma 8-9, openSUSE Leap)
    case "$PKG" in
        apt)     NEED2=(python3.11 python3.11-venv) ;;
        dnf|yum) NEED2=(python3.11 python3.11-pip) ;;
        zypper)  NEED2=(python311 python311-pip) ;;
        *)       NEED2=() ;;
    esac
    ask "Install Python 3.11+ now (${NEED[*]}, or ${NEED2[*]:-nothing else} if the default is older)?" y || die "Python 3.11+ is required."
    pkg_install "${NEED[@]}" || true
    PY="$(find_python || true)"
    if [[ -z "$PY" && ${#NEED2[@]} -gt 0 ]]; then
        pkg_install "${NEED2[@]}" || true
        PY="$(find_python || true)"
    fi
    [[ -z "$PY" ]] && die "Python 3.11+ still not found. Install Python 3.11 or newer for your distribution, then run this again."
fi
c_ok "✔ Using $($PY --version) ($PY)"

if ! "$PY" -m venv --help >/dev/null 2>&1 || ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
    case "$PKG" in
        apt) PYVER="$("$PY" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"
             ask "Install python${PYVER}-venv (needed for a private Python environment)?" y || die "python3-venv is required."
             pkg_install "python${PYVER}-venv" || pkg_install python3-venv ;;
        *)   c_warn "Python venv/ensurepip missing; trying python3-pip"; pkg_install python3-pip || true ;;
    esac
fi

# PAM library (normally present; python-pam loads libpam.so.0)
if ! "$PY" -c 'import ctypes.util, sys; sys.exit(0 if ctypes.util.find_library("pam") else 1)' 2>/dev/null; then
    case "$PKG" in
        apt) pkg_install libpam0g ;; dnf|yum) pkg_install pam ;; zypper) pkg_install pam ;;
    esac
fi

# ------------------------------------------------------------- stop older copies / NoteVault
HAVE_SYSTEMD=0
if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then HAVE_SYSTEMD=1; fi

if [[ $HAVE_SYSTEMD -eq 1 ]]; then
    systemctl --user stop "${APP}.service" 2>/dev/null || true
    if systemctl --user is-active --quiet notevault-app.service 2>/dev/null || systemctl --user is-enabled --quiet notevault-app.service 2>/dev/null; then
        c_warn "NoteVault (the old version) is running and uses port ${PORT}."
        if ask "Stop and disable the NoteVault services? (its files and data are left untouched)" y; then
            systemctl --user disable --now notevault-app.service notevault-webdav.service 2>/dev/null || true
            c_ok "✔ NoteVault services stopped and disabled"
        fi
    fi
fi

# ------------------------------------------------------------- copy app
c_info "📁 Installing to $APP_DIR"
mkdir -p "$APP_DIR" "$DATA_DIR"/{notes,backups,Logs}
chmod 700 "$DATA_DIR"
rm -rf "$APP_DIR/templates" "$APP_DIR/static"
cp "$SCRIPT_DIR"/Pustakam*.py "$SCRIPT_DIR/PustakamRequirements.txt" "$APP_DIR/"
cp -r "$SCRIPT_DIR/templates" "$SCRIPT_DIR/static" "$APP_DIR/"
cp "$SCRIPT_DIR/PustakamUninstall.sh" "$INSTALL_DIR/" && chmod +x "$INSTALL_DIR/PustakamUninstall.sh"

c_info "🐍 Creating Python environment"
"$PY" -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip -q
"$VENV_DIR/bin/python" -m pip install -r "$APP_DIR/PustakamRequirements.txt" -q
c_ok "✔ Python packages installed"

# ------------------------------------------------------------- rclone (OneDrive sign-in & sync)
rclone_ok() {  # usable = version 1.58 or newer
    local v; v="$("$1" version 2>/dev/null | head -1 | sed -E 's/^rclone v?([0-9]+)\.([0-9]+).*/\1 \2/')"
    [[ -n "$v" ]] && read -r MA MI <<<"$v" && { [[ $MA -gt 1 ]] || [[ $MI -ge 58 ]]; }
}
if [[ -x "$INSTALL_DIR/bin/rclone" ]] && rclone_ok "$INSTALL_DIR/bin/rclone"; then
    c_ok "✔ rclone: $("$INSTALL_DIR/bin/rclone" version | head -1) (Pustakam's copy)"
elif command -v rclone >/dev/null 2>&1 && rclone_ok "$(command -v rclone)"; then
    c_ok "✔ rclone: $(rclone version | head -1) (system)"
else
    c_info "OneDrive sign-in uses rclone (no Microsoft app registration needed)."
    if ask "Download the official rclone build (~25 MB, checksum-verified) into $INSTALL_DIR/bin?" y; then
        "$VENV_DIR/bin/python" "$APP_DIR/PustakamGetRclone.py" "$INSTALL_DIR/bin" || c_warn "rclone download failed; OneDrive will not work until rclone is installed."
    else
        c_warn "Skipped. Install rclone 1.58+ later for OneDrive (https://rclone.org/install/)."
    fi
fi

# ------------------------------------------------------------- migrate NoteVault data
if [[ -f "$HOME/.notevault/notevault.db" && ! -f "$DATA_DIR/pustakam.db" ]]; then
    if ask "Copy your NoteVault notes into Pustakam? (NoteVault's own files are not changed)" y; then
        "$VENV_DIR/bin/python" - "$HOME/.notevault/notevault.db" "$DATA_DIR/pustakam.db" <<'PYEOF'
import sqlite3, sys
src, dst = sqlite3.connect(sys.argv[1]), sqlite3.connect(sys.argv[2])
with dst: src.backup(dst)
PYEOF
        [[ -d "$HOME/.notevault/notes" ]] && cp -rn "$HOME/.notevault/notes/." "$DATA_DIR/notes/" 2>/dev/null || true
        c_ok "✔ NoteVault notes copied"
    fi
fi

( cd "$APP_DIR" && "$VENV_DIR/bin/python" -c "import PustakamDatabase as d; d.init_db(); print('🗄️  Database ready')" )

# ------------------------------------------------------------- service + daily backup
if [[ $HAVE_SYSTEMD -eq 1 ]]; then
    c_info "⚙️  Installing systemd user service"
    mkdir -p "$UNIT_DIR"
    cat > "$UNIT_DIR/${APP}.service" <<EOF
[Unit]
Description=Pustakam (पुस्तकम्) notes server
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/PustakamApp.py
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
    cat > "$UNIT_DIR/${APP}-backup.service" <<EOF
[Unit]
Description=Pustakam daily backup

[Service]
Type=oneshot
WorkingDirectory=${APP_DIR}
ExecStart=${VENV_DIR}/bin/python ${APP_DIR}/PustakamBackup.py
EOF
    cat > "$UNIT_DIR/${APP}-backup.timer" <<EOF
[Unit]
Description=Run Pustakam backup every day at 21:00

[Timer]
OnCalendar=*-*-* 21:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl --user daemon-reload
    systemctl --user enable --now "${APP}.service"
    systemctl --user enable --now "${APP}-backup.timer"
    # keep running after logout / start at boot
    loginctl enable-linger "$USER" 2>/dev/null || $SUDO loginctl enable-linger "$USER" 2>/dev/null || \
        c_warn "Could not enable lingering; Pustakam will start when you log in."
    c_ok "✔ Service started"
else
    c_warn "systemd user services are not available (e.g. sysvinit). Using cron instead."
    if ! command -v crontab >/dev/null 2>&1; then
        case "$PKG" in apt) pkg_install cron ;; dnf|yum) pkg_install cronie ;; zypper) pkg_install cronie ;; esac
    fi
    START="cd ${APP_DIR} && nohup ${VENV_DIR}/bin/python ${APP_DIR}/PustakamApp.py >> ${DATA_DIR}/Logs/server.log 2>&1 &"
    ( crontab -l 2>/dev/null | grep -v 'Pustakam' || true
      echo "@reboot ${START} # Pustakam server"
      echo "0 21 * * * cd ${APP_DIR} && ${VENV_DIR}/bin/python ${APP_DIR}/PustakamBackup.py >> ${DATA_DIR}/Logs/backup-cron.log 2>&1 # Pustakam backup"
    ) | crontab -
    pkill -f "${APP_DIR}/PustakamApp.py" 2>/dev/null || true
    bash -c "$START"
    c_ok "✔ Started (and scheduled with cron @reboot)"
fi

# ------------------------------------------------------------- firewall (LAN access)
if command -v firewall-cmd >/dev/null 2>&1 && $SUDO firewall-cmd --state >/dev/null 2>&1; then
    if ask "Open port ${PORT}/tcp in firewalld so other devices on your network can reach Pustakam?" n; then
        $SUDO firewall-cmd --permanent --add-port=${PORT}/tcp && $SUDO firewall-cmd --reload && c_ok "✔ firewalld: port ${PORT} open"
    fi
elif command -v ufw >/dev/null 2>&1 && $SUDO ufw status 2>/dev/null | grep -q "Status: active"; then
    if ask "Open port ${PORT}/tcp in ufw so other devices on your network can reach Pustakam?" n; then
        $SUDO ufw allow ${PORT}/tcp comment 'Pustakam' && c_ok "✔ ufw: port ${PORT} open"
    fi
fi

# ------------------------------------------------------------- desktop launcher
mkdir -p "$(dirname "$DESKTOP_FILE")"
cp "$SCRIPT_DIR/static/img/PustakamLogo.svg" "$INSTALL_DIR/PustakamLogo.svg"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Pustakam
GenericName=Notes
Comment=पुस्तकम् — Markdown notebooks with cloud sync
Exec=xdg-open http://localhost:${PORT}/
Icon=${INSTALL_DIR}/PustakamLogo.svg
Terminal=false
Categories=Office;Utility;
EOF

sleep 2
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo ""
echo "=================================================="
c_ok   "  ✅ Pustakam v${PK_VERSION} is installed"
echo "=================================================="
echo "  🌐 Open:        http://localhost:${PORT}   ${IP:+(LAN: http://${IP}:${PORT})}"
echo "  🔐 Sign in as:  $(id -un)  with your Linux password"
echo "  📁 Data:        $DATA_DIR"
echo "  📦 Program:     $INSTALL_DIR"
if [[ $HAVE_SYSTEMD -eq 1 ]]; then
echo "  🔧 Manage:      systemctl --user status|restart|stop ${APP}"
echo "  📜 Logs:        $DATA_DIR/Logs  (and: journalctl --user -u ${APP} -f)"
fi
echo "  ☁️  OneDrive:    Settings → Sign in with Microsoft"
echo "  💾 Backups:     daily 21:00 → $DATA_DIR/backups (change in Settings)"
echo "  🗑️  Uninstall:   $INSTALL_DIR/PustakamUninstall.sh"
echo ""
