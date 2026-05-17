# KDE Discourse — release announcement

URL: https://discuss.kde.org/c/community/release-announcements/

**Title:**
> gdrive-mgr 0.1.0 — Google Drive for KDE Plasma 6 (rclone-based, with Dolphin badges and in-app sharing)

**Body:** (Markdown supported)

> Hi all,
>
> I've just released **gdrive-mgr** 0.1.0, a Google Drive client for KDE Plasma 6. It wraps **rclone** to give Linux desktops the same on-demand-with-pinning experience that Google Drive Desktop provides on Windows and macOS.
>
> **Highlights:**
>
> - On-demand FUSE mount at `~/GoogleDrive/<account>/` — files download only when opened.
> - Right-click in Dolphin → *Google Drive → Keep always on this device* — folder or single file becomes locally synced (bisync for folders, copyto + polling for files).
> - Reactive sync via inotify — local edits push within seconds.
> - **C++ KOverlayIconPlugin** for per-file Dolphin badges (synced/syncing/error/online-only).
> - Native Qt share dialog (no browser hop) for adding people by email at Viewer/Commenter/Editor level.
> - Multi-account support, conflict resolution UI, disk-usage breakdown, color-coded tray.
>
> **GitHub (with screenshots and install instructions):**
> https://github.com/KSM899/gdrive-mgr
>
> **Tested on:** Fedora 44 / KDE Plasma 6.4. Should work on any systemd distro with KDE; would love feedback from other distro users.
>
> **License:** GPL-3.0-or-later. **Stack:** Python (PySide6) + a small C++ Qt plugin.
>
> Bug reports / feature ideas / packaging help all welcome on the issue tracker.

**Tags:** `release`, `dolphin`, `cloud-storage`, `google-drive`
