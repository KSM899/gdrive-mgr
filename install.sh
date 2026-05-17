#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
#
# gdrive-mgr installer (user-local, no root needed for the GUI/CLI bits).
#
# Sets up:
#   1. Python venv at <project>/.venv  (with PySide6 + watchdog)
#   2. ~/.local/bin/gdrive-mgr        — symlink to the launcher
#   3. ~/.local/bin/gdrive-mgr-cli    — symlink to the CLI wrapper
#   4. ~/.local/share/applications/   — KDE app launcher
#   5. ~/.local/share/kio/servicemenus/ — Dolphin right-click menu
#   6. ~/.config/systemd/user/        — mount + daemon systemd units
#   7. gdrive-mgr-daemon.service      — started immediately
#
# The Dolphin overlay plugin (C++) is OPTIONAL and installed separately:
#   ./plugin/build.sh   (needs sudo for system Qt plugin path)

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
APPS_DIR="$HOME/.local/share/applications"
SVC_DIR="$HOME/.local/share/kio/servicemenus"
BIN_DIR="$HOME/.local/bin"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }
warn(){ printf '\033[1;33m  !\033[0m %s\n' "$*" >&2; }
die() { printf '\033[1;31m  ✗\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 1. dependency check ----
say "Checking system dependencies"

command -v rclone        >/dev/null 2>&1 || die "rclone is required. Install: sudo dnf install rclone"
command -v fusermount3   >/dev/null 2>&1 || die "fusermount3 (fuse3) is required. Install: sudo dnf install fuse3"
command -v python3       >/dev/null 2>&1 || die "python3 is required"
command -v systemctl     >/dev/null 2>&1 || die "systemctl is required (systemd-based distro)"

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
ok "rclone $(rclone version | head -1 | awk '{print $2}'), fuse3, python $PY_VERSION, systemd"

# ---- 2. python venv + deps ----
say "Setting up Python environment at $PROJECT_DIR/.venv"

if [ ! -d "$PROJECT_DIR/.venv" ]; then
    python3 -m venv "$PROJECT_DIR/.venv"
    ok "Created venv"
fi

"$PROJECT_DIR/.venv/bin/pip" install --quiet --upgrade pip
"$PROJECT_DIR/.venv/bin/pip" install --quiet 'PySide6>=6.6' 'watchdog>=4.0'
ok "Installed PySide6 + watchdog"

# ---- 3. bin symlinks ----
say "Linking executables into $BIN_DIR"

mkdir -p "$BIN_DIR"
ln -sf "$PROJECT_DIR/bin/gdrive-mgr"     "$BIN_DIR/gdrive-mgr"
ln -sf "$PROJECT_DIR/bin/gdrive-mgr-cli" "$BIN_DIR/gdrive-mgr-cli"
ok "gdrive-mgr, gdrive-mgr-cli"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) warn "$BIN_DIR is not in your PATH. Add this to ~/.bashrc or ~/.zshrc:"
       warn "    export PATH=\"\$HOME/.local/bin:\$PATH\""
       ;;
esac

# ---- 4. .desktop files ----
say "Installing desktop integration"

mkdir -p "$APPS_DIR" "$SVC_DIR"

# Substitute @BINDIR@ in the .desktop templates with the user's local bin path.
sed "s|@BINDIR@|$BIN_DIR|g" "$PROJECT_DIR/resources/io.github.gdrive_mgr.desktop.in" \
    > "$APPS_DIR/io.github.gdrive_mgr.desktop"
sed "s|@BINDIR@|$BIN_DIR|g" "$PROJECT_DIR/resources/gdrive-mgr-pin.desktop.in" \
    > "$SVC_DIR/gdrive-mgr-pin.desktop"
chmod +x "$SVC_DIR/gdrive-mgr-pin.desktop"
ok "App launcher  → $APPS_DIR/io.github.gdrive_mgr.desktop"
ok "Service menu  → $SVC_DIR/gdrive-mgr-pin.desktop"

if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental 2>/dev/null || true
fi

# ---- 5. systemd units + start daemon ----
say "Setting up systemd units"

"$PROJECT_DIR/.venv/bin/python" - <<'PY'
from gdrive_mgr.systemd_units import ensure_template_units, daemon_active, start_daemon
ensure_template_units()
if not daemon_active():
    start_daemon()
    print("  ✓ daemon started")
else:
    print("  ✓ daemon already running")
PY

# ---- done ----
echo
say "Installation complete."
echo
echo "  Run the GUI:      gdrive-mgr  (or 'Google Drive Manager' in your app launcher)"
echo "  Add an account:   Toolbar → Add account"
echo "  Right-click any folder/file in Dolphin under your Drive mount → Google Drive submenu"
echo
echo "Optional — Dolphin per-file sync badges (requires sudo + build deps):"
echo "    sudo dnf install cmake gcc-c++ qt6-qtbase-devel kf6-kio-devel extra-cmake-modules"
echo "    $PROJECT_DIR/plugin/build.sh"
echo
echo "To remove: $PROJECT_DIR/uninstall.sh"
