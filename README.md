# gdrive-mgr

[![License: GPL v3+](https://img.shields.io/badge/license-GPL--3.0--or--later-blue.svg)](LICENSE)
[![Latest release](https://img.shields.io/github/v/release/KSM899/gdrive-mgr?label=release)](https://github.com/KSM899/gdrive-mgr/releases/latest)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Qt](https://img.shields.io/badge/Qt-6-41cd52.svg)](https://www.qt.io/)
[![Platform](https://img.shields.io/badge/platform-KDE%20Plasma%206-1d99f3.svg)](https://kde.org/plasma-desktop/)
[![Stars](https://img.shields.io/github/stars/KSM899/gdrive-mgr?style=social)](https://github.com/KSM899/gdrive-mgr/stargazers)

**A KDE-native Google Drive manager for Linux** — files-on-demand mount, per-folder and per-file pinning, background sync, in-app sharing, and Dolphin overlay badges. Built on [rclone](https://rclone.org).

If you've used Google Drive Desktop on Windows or macOS and missed the same experience on KDE Plasma, this fills that gap.

> Built fully using AI by **Khalid Said**.

---

## What it does

- **Mounts your Drive on demand** at `~/GoogleDrive/<account>/` — your whole Drive appears as a regular folder; files only download when you open them.
- **"Keep always on this device"** on any folder or file: right-click in Dolphin → *Google Drive → Keep always on this device*. The item gets a real local copy at `~/GoogleDrive-Offline/<account>/...`, kept in two-way sync via `rclone bisync` (folders) or `rclone copyto` + polling (files).
- **Reactive background sync** via inotify — local edits propagate to Drive within seconds, not minutes.
- **Dolphin overlay badges** ⭐ ✓ ⚠ ☁ on every file/folder so you can tell at a glance what's synced, syncing, online-only, or in error.
- **In-app sharing** — a native Qt dialog for adding people, setting Viewer/Commenter/Editor roles, sending notification emails, and revoking access. No browser hop.
- **Shareable links** — right-click → *Copy shareable link*; URL goes straight to your clipboard.
- **Multiple Google accounts** side by side — each gets its own mount + offline tree.
- **Conflict resolution UI** for the inevitable bisync conflict files.
- **Disk usage panel** showing real on-disk footprint per account (broken out by VFS cache, pinned folders, pinned files) — not the misleading "apparent size" your file manager shows.

## Screenshots

_(Add your own under `docs/screenshots/`.)_

---

## Why another Drive client?

The Linux Drive client landscape:

| Option | Issue |
|---|---|
| Google Drive Desktop | Doesn't exist for Linux. |
| GNOME Online Accounts | GNOME-only, no offline mode, no overlays. |
| KIO GDrive | Buggy on Plasma 6, no offline pinning. |
| Insync | Paid, closed-source. |
| Raw rclone mount | Powerful but no GUI, no per-file pinning, no badges, no integration. |
| Nextcloud client | Different service. |

gdrive-mgr wraps rclone with a proper Plasma 6 experience: a tray icon, a tabbed app for accounts and conflicts, a Dolphin service menu, and a native overlay-icon plugin.

---

## Requirements

| | |
|---|---|
| OS | Linux (developed on Fedora 44, should work on any systemd distro) |
| Desktop | KDE Plasma 6 (Plasma 5 untested; many features assume Plasma 6) |
| Python | 3.11+ |
| Required packages | `rclone`, `fuse3` |
| For per-file Dolphin badges (optional) | `cmake`, `gcc-c++`, `qt6-qtbase-devel`, `kf6-kio-devel`, `extra-cmake-modules` |

On Fedora:

```bash
sudo dnf install rclone fuse3
```

For the optional Dolphin overlay-badge plugin:

```bash
sudo dnf install cmake gcc-c++ qt6-qtbase-devel kf6-kio-devel extra-cmake-modules
```

---

## Install

```bash
git clone https://github.com/KSM899/gdrive-mgr.git
cd gdrive-mgr
./install.sh
```

`install.sh` does everything user-local (no `sudo`):

- creates a Python venv in `.venv/` with PySide6 + watchdog
- symlinks `gdrive-mgr` and `gdrive-mgr-cli` into `~/.local/bin/`
- installs the KDE app launcher and Dolphin service menu
- writes the systemd user units and starts the sync daemon

If `~/.local/bin` isn't already in your `PATH`, the installer will tell you.

### Optional — Dolphin overlay badges

The C++ KOverlayIconPlugin gives you per-file ✓ / ⏳ / ⚠ / ☁ badges in Dolphin. It needs system Qt6 and KF6 dev packages, and the build installs to a system path (so `sudo` is required for that one step):

```bash
./plugin/build.sh   # configures, builds, sudo installs, refreshes KDE plugin cache
```

You can skip this — the rest of the app works fine without per-file badges (you still get a colored tray icon for global state).

---

## First-time setup

1. Run **`gdrive-mgr`** (or open *Google Drive Manager* from your app launcher).
2. Click **Add account** in the toolbar.
3. Pick an identifier (e.g. `personal`, `work`) and a display name.
4. The OAuth flow opens in your browser. When Google shows *"Google hasn't verified this app"*, click **Advanced → Go to rclone (unsafe)** and grant all the requested permissions. (The app being unverified is normal — see the [Security](SECURITY.md) doc for what's happening.)
5. Once authorized, click **Mount** in the toolbar. Your Drive appears at `~/GoogleDrive/<identifier>/`.

The mount is the **on-demand** view: every file looks like a regular file but is streamed from the cloud the first time you open it.

---

## Daily use

### Pin a folder for offline access

Right-click a folder under `~/GoogleDrive/<account>/` in Dolphin → **Google Drive → Keep always on this device**. The folder is bisynced to `~/GoogleDrive-Offline/<account>/<folder>` and from then on:

- Local edits propagate to Drive within a few seconds (inotify-driven).
- Cloud edits propagate to local within ~60s (poll), or immediately on app focus.
- The Dolphin badge tracks the state.

### Pin a single file

Same as a folder — right-click the file (anywhere in the mount) → **Google Drive → Keep always on this device**. A `_FileSyncWorker` watches just that file and bidirectionally syncs with `rclone copyto`.

### Free up space

Right-click a pinned folder or file → **Google Drive → Make online-only (free space)**. The local copy is deleted; the file remains in Drive and stays browsable via the mount.

### Share

Right-click any file or folder → **Google Drive → Share with others…**. A native Qt dialog opens where you can:

- Add people by email at Viewer / Commenter / Editor level
- Toggle email notification + add a personal message
- See current shares, including the "anyone with link" permissions
- Revoke access

Or **Google Drive → Copy shareable link** for a quick anyone-with-link URL straight to your clipboard.

### Sync now

Right-click → **Google Drive → Sync now** triggers an immediate bisync (or copyto for files), useful when you've just made an important edit and don't want to wait the few seconds for the debounce.

---

## The app

| Tab | What it does |
|---|---|
| **Status** | Mount state, Drive storage usage, per-pin summary |
| **Browse & Pin** | Walk your Drive folder tree; checkbox for "Available offline" per folder |
| **Conflicts** | bisync conflict files with keep-local / keep-remote / open-diff actions |
| **Disk Usage** | Real on-disk footprint per account (VFS cache + pinned folders + pinned files) |

A **system tray icon** is always visible:

- 🟢 green dot — all synced
- 🟡 amber — sync in progress
- 🔴 red — at least one folder has an error

Clicking the tray opens the app; right-clicking gives quick mount/unmount toggles per account and a *Sync all* per pin.

---

## Architecture

```
                       ┌─────────────────────────────────┐
                       │       gdrive-mgr GUI (Qt)       │
                       │   account add, browse, pin UI,  │
                       │   conflicts, disk usage, share  │
                       └────────────────┬────────────────┘
                                        │ ConfigStore (flock'd JSON)
                                        ▼
        ┌─────────────────────┐  ┌──────────────────┐  ┌───────────────┐
        │  Dolphin right-     │  │  systemd: gdrive │  │   Tray icon   │
        │  click .desktop     │──│  -mgr-daemon     │──│   (colors)    │
        │  → gdrive-mgr-cli   │  │   (inotify +     │  └───────────────┘
        │                     │  │    bisync/copy)  │
        └─────────────────────┘  └─────────┬────────┘
                                           │ ~/.cache/gdrive-mgr/status.json
                                           ▼
                                  ┌──────────────────┐
                                  │  Dolphin overlay │
                                  │  plugin (C++)    │
                                  │  per-file badges │
                                  └──────────────────┘
                                           │
                                           ▼
        ┌─────────────────────────────────────────────────────────────┐
        │       rclone (mount + bisync + copyto + drive backend)      │
        └─────────────────────────────────────────────────────────────┘
```

- **`gdrive_mgr/` Python package** — all the GUI, daemon, CLI, and orchestration logic
- **`plugin/` C++ subproject** — KOverlayIconPlugin for Dolphin badges
- **`resources/`** — `.desktop` templates and the QSS stylesheet
- **`bin/`** — thin wrapper scripts that activate the venv and exec Python

The daemon is the single owner of `status.json`; every other component (tray, app panels, Dolphin plugin) only reads it.

Detailed module breakdown:

| File | Responsibility |
|---|---|
| `gdrive_mgr/__main__.py` | App entry point — style/QSS, tray, main window |
| `gdrive_mgr/config.py` | Account + pin persistence, cross-process fcntl-locked JSON |
| `gdrive_mgr/rclone.py` | Subprocess wrapper around the rclone CLI |
| `gdrive_mgr/drive_api.py` | Direct Drive REST calls for sharing (re-uses rclone's OAuth token) |
| `gdrive_mgr/daemon.py` | `_SyncWorker` (folders/bisync) + `_FileSyncWorker` (files/copyto) + IPC socket |
| `gdrive_mgr/systemd_units.py` | Templated user units for mount/pin/daemon |
| `gdrive_mgr/cli.py` | All CLI subcommands (invoked by Dolphin and systemd) |
| `gdrive_mgr/status.py` | The `status.json` source-of-truth for badges |
| `gdrive_mgr/ui/*` | Qt widgets for each tab + dialogs |
| `plugin/GDriveOverlayPlugin.cpp` | Dolphin overlay-icon plugin (KOverlayIconPlugin subclass) |

---

## Troubleshooting

**Daemon log:**

```bash
journalctl --user -u gdrive-mgr-daemon.service -f
```

**Mount log:**

```bash
journalctl --user -u 'gdrive-mount@*.service' -f
```

**Anything broken:**

```bash
systemctl --user --failed
```

**Restart the mount after editing config:**

```bash
systemctl --user restart 'gdrive-mount@*.service'
```

**Common issues:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `fusermount3: Permission denied` on mount | Old FUSE mount at the same path | `fusermount3 -u ~/GoogleDrive/<account>` |
| "Empty current Path2" bisync error | bisync history mismatch | Daemon auto-recovers with `--resync` on next run |
| Right-click menu missing | Service menu file not installed or Dolphin not restarted | `./install.sh`, then `kquitapp6 dolphin && dolphin &` |
| Badges don't appear | Dolphin started before the plugin was installed | restart Dolphin |
| Browser opens to `127.0.0.1:.../%22` during OAuth | (Old bug, fixed in 0.1.0) | upgrade |

---

## Uninstall

```bash
./uninstall.sh
```

This stops services, unmounts all Drive accounts, and removes the desktop integration and systemd units. It leaves your **rclone account config**, **local pinned copies**, and **gdrive-mgr settings** alone — delete those manually if you want.

To also remove the optional Dolphin overlay plugin:

```bash
sudo rm /usr/lib64/qt6/plugins/kf6/overlayicon/gdrivemgroverlay.so
```

---

## Limitations

- **rclone bisync is upstream-beta.** Conflict files (`*.conflict<n>`) appear occasionally; that's why the Conflicts tab exists.
- **First bisync of a large folder is slow** — it has to enumerate both sides.
- **Pinning a deep folder when an ancestor is already pinned will duplicate data.** Pick one level.
- **Per-file pin uses polling for cloud-side changes** (default 60s). The daemon doesn't subscribe to Drive's change-notification webhook — that would need a public callback URL.
- **No support for Shared Drives or Team Drives** in the current pin UI (the underlying rclone supports it, just no GUI yet).
- **Mount cache size is fixed at 10 GB** per account in the systemd unit template — edit `gdrive_mgr/systemd_units.py` if you want different.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Bug reports and feature suggestions are welcome via GitHub Issues.

## License

Copyright © 2026 Khalid Said.

Released under the **GNU General Public License v3.0 or later** — see [LICENSE](LICENSE) for the full text and [SECURITY.md](SECURITY.md) for the security model and credential-handling notes.

The Dolphin overlay plugin is also GPL-3.0-or-later and links against KDE Frameworks 6 (LGPL).

---

*Built fully using AI by Khalid Said.*
