#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
#
# Reverses install.sh: stops services, unmounts all Drive accounts, removes
# desktop integration and systemd units. Does NOT touch:
#   - your rclone config (~/.config/rclone/) — your Google account stays linked
#   - your downloaded/pinned local copies (~/GoogleDrive-Offline/)
#   - the project source itself
# Delete those manually if you want.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
APPS_DIR="$HOME/.local/share/applications"
SVC_DIR="$HOME/.local/share/kio/servicemenus"
BIN_DIR="$HOME/.local/bin"
USER_SYSTEMD="$HOME/.config/systemd/user"

say() { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()  { printf '\033[1;32m  ✓\033[0m %s\n' "$*"; }

# Stop & disable everything we created.
say "Stopping services"
for unit in $(systemctl --user list-units --all --no-legend 'gdrive-*' 2>/dev/null | awk '{print $1}'); do
    systemctl --user disable --now "$unit" 2>/dev/null || true
    ok "stopped $unit"
done
# Unmount any leftover FUSE mounts under ~/GoogleDrive
for m in "$HOME"/GoogleDrive/*/; do
    [ -d "$m" ] || continue
    fusermount3 -u "$m" 2>/dev/null && ok "unmounted $m" || true
done

# Remove unit files.
say "Removing systemd units"
rm -fv "$USER_SYSTEMD"/gdrive-mount@.service \
       "$USER_SYSTEMD"/gdrive-pin@.service \
       "$USER_SYSTEMD"/gdrive-pin@.timer \
       "$USER_SYSTEMD"/gdrive-mgr-daemon.service 2>/dev/null
systemctl --user daemon-reload 2>/dev/null || true

# Remove desktop integration.
say "Removing desktop integration"
rm -fv "$APPS_DIR/io.github.gdrive_mgr.desktop" \
       "$SVC_DIR/gdrive-mgr-pin.desktop" \
       "$BIN_DIR/gdrive-mgr" \
       "$BIN_DIR/gdrive-mgr-cli" 2>/dev/null

if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental 2>/dev/null || true
fi

# Optional plugin uninstall
PLUGIN_PATH=/usr/lib64/qt6/plugins/kf6/overlayicon/gdrivemgroverlay.so
if [ -f "$PLUGIN_PATH" ]; then
    echo
    echo "The Dolphin overlay plugin is still installed at:"
    echo "  $PLUGIN_PATH"
    echo "To remove: sudo rm $PLUGIN_PATH"
fi

# Final notes
echo
ok "gdrive-mgr is uninstalled."
echo
echo "Left in place (delete manually if desired):"
echo "  - rclone account config: ~/.config/rclone/"
echo "  - gdrive-mgr settings:   ~/.config/gdrive-mgr/"
echo "  - status cache:          ~/.cache/gdrive-mgr/"
echo "  - downloaded copies:     ~/GoogleDrive-Offline/   (your local files!)"
echo "  - source tree:           $PROJECT_DIR"
