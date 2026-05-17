#!/usr/bin/env bash
# Configure + build + install the Dolphin overlay-icon plugin.
# Requires: cmake, gcc-c++, qt6-qtbase-devel, kf6-kio-devel, extra-cmake-modules
# Plugin must be installed system-wide (Dolphin only loads from Qt's library
# paths), so the install step uses sudo.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$SCRIPT_DIR"

cmake -S . -B build -G Ninja
cmake --build build

echo
echo "Plugin built: $SCRIPT_DIR/build/bin/kf6/overlayicon/gdrivemgroverlay.so"
echo "Installing (requires sudo)…"
sudo cmake --install build

# Refresh Plasma's plugin cache so Dolphin discovers the new plugin without
# requiring a full session restart.
if command -v kbuildsycoca6 >/dev/null 2>&1; then
    kbuildsycoca6 --noincremental
fi
if pgrep -x dolphin >/dev/null 2>&1; then
    echo "Restart Dolphin to load the plugin: kquitapp6 dolphin && dolphin &"
fi
