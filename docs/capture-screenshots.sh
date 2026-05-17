#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
#
# Walk-through script to capture all the screenshots listed in
# docs/screenshots/README.md. Uses spectacle in active-window mode so you
# just need to focus the right window before pressing Enter.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
OUT_DIR="$SCRIPT_DIR/screenshots"
mkdir -p "$OUT_DIR"

command -v spectacle >/dev/null 2>&1 || {
    echo "spectacle is required. Install: sudo dnf install spectacle"
    exit 1
}

capture() {
    local name="$1"
    local prompt="$2"
    echo
    echo "  $prompt"
    echo "  Press Enter when ready (or 's' to skip)..."
    read -r ans
    [ "$ans" = "s" ] && { echo "  skipped"; return; }
    # 2-second delay so you can focus the right window after the keypress
    # if you accidentally focused this terminal.
    sleep 2
    spectacle --background --activewindow --nonotify \
              --output "$OUT_DIR/$name.png"
    echo "  saved $OUT_DIR/$name.png"
}

echo "============================================================"
echo "  gdrive-mgr screenshot capture"
echo "============================================================"
echo
echo "  Make sure the app is running: 'gdrive-mgr &' in another terminal."
echo "  For each prompt, click the window you want captured, then press Enter."

capture main-window  "Focus the main window on the Status tab"
capture browse-pin   "Switch to the Browse & Pin tab, expand the tree"
capture disk-usage   "Switch to the Disk Usage tab and click Refresh"
capture share-dialog "Right-click a file in Dolphin → Google Drive → Share with others… and add a test person"
capture dolphin-menu "Right-click a folder in your Drive mount in Dolphin (capture context menu open)"
capture dolphin-badges "Browse your offline-pinned folder in Dolphin to show overlay badges"
capture tray         "Click the gdrive-mgr tray icon to open its menu"

echo
echo "Done. Captured files in: $OUT_DIR"
echo "Commit + push:"
echo "    git add docs/screenshots/*.png && git commit -m 'docs: screenshots' && git push"
