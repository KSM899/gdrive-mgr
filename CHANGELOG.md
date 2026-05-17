# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] — 2026-05-17

Initial public release.

### Added

- **On-demand FUSE mount** per Google account via `rclone mount` with
  systemd user-unit lifecycle (`gdrive-mount@<remote>.service`).
- **Per-folder pinning** with bidirectional `rclone bisync`, auto-managed
  by a systemd timer (`gdrive-pin@<instance>.timer`).
- **Per-file pinning** with `rclone copyto` + inotify (push) and
  configurable cloud-side polling (pull).
- **Background daemon** (`gdrive-mgr-daemon.service`) that owns the inotify
  watchers, debounce queues, conflict detection, and writes `status.json`
  for badges.
- **Dolphin right-click service menu** with five actions:
    - Keep always on this device
    - Make online-only (free space)
    - Sync now
    - Copy shareable link
    - Share with others…
- **Native Qt share dialog** that talks directly to the Drive REST API,
  re-using rclone's OAuth token (no browser hop).
- **Dolphin overlay-icon plugin** (C++ KOverlayIconPlugin) showing per-file
  badges: synced ✓, syncing ⏳, error ⚠, online-only ☁.
- **Multi-account support** — each Google account gets its own mount,
  offline tree, and badge.
- **System tray icon** with color-coded global state (green/amber/red) and
  per-account quick toggles.
- **Bisync conflict resolution UI** (Conflicts tab): keep local, keep
  remote, open diff.
- **Disk-usage breakdown** (Disk Usage tab): real on-disk footprint per
  account, broken out by VFS cache, pinned folders, pinned files.
- **Cross-process safe config** — every mutation re-reads under `fcntl.flock`
  to prevent stale-snapshot clobber.
- **Modern QSS stylesheet** for a flat KDE-ish look that adapts to the
  active Qt palette.
- **About dialog** with version, attribution, and license info.
- **GPL-3.0-or-later license**, SPDX headers on every source file.
- **`SECURITY.md`** documenting the threat model, secret storage, and
  network surface.

[0.1.0]: https://github.com/KSM899/gdrive-mgr/releases/tag/v0.1.0
