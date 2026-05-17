# Reddit posts

Three subreddits, three slightly different angles. Cross-post manually
rather than using Reddit's crosspost feature — each subreddit prefers a
custom take.

Best posting times: **Tue–Thu, 10am–1pm ET** (peak desktop browsing).

Read each sub's rules before posting; some require flair, some forbid
"self-promotion" without prior comment activity.

---

## r/kde

**Title:**
> [Release] gdrive-mgr — Google Drive for KDE Plasma with Dolphin overlay badges and in-app sharing

**Body:**

> I made a KDE Plasma 6 Google Drive client because nothing on Linux gives the same on-demand-plus-pinning experience that Google Drive Desktop has on Windows/macOS. Built on rclone.
>
> **What you get:**
>
> - Files-on-demand FUSE mount at `~/GoogleDrive/<account>/`
> - Right-click any folder/file in Dolphin → "Keep always on this device" (real local copy, bidirectional sync)
> - Per-file Dolphin overlay badges (synced/syncing/error/online-only) via a small C++ KOverlayIconPlugin
> - Native Qt share dialog (no browser hop) for adding people by email
> - Multiple Google accounts side by side
> - Color-coded tray + bisync conflict UI
>
> GPL-3.0. Python + a 200-line C++ Qt plugin.
>
> Source + screenshots: https://github.com/KSM899/gdrive-mgr
>
> Tested on Fedora 44 / Plasma 6.4. Would love feedback from other distros.

Add the **[Release]** or **[Tool]** flair if the sub has them.

---

## r/linux

**Title:**
> Released gdrive-mgr 0.1.0 — open-source Google Drive client for KDE Plasma 6 with files-on-demand and Dolphin integration

**Body:**

> Frustrated by the gap between Google Drive Desktop on Windows/macOS and what's available on Linux (KIO GDrive is buggy on Plasma 6, Insync is paid, raw rclone has no GUI), I built **gdrive-mgr** to fill it.
>
> **Why it's different from `rclone mount` alone:**
>
> - Real KDE integration: right-click menu in Dolphin, overlay badges, system tray
> - Per-folder AND per-file "Keep always on this device" (rclone bisync for folders, rclone copyto + polling for single files)
> - Native Qt share dialog using the Drive REST API directly — no browser bounce
> - Multi-account, conflict resolution UI, disk-usage breakdown
>
> Stack: Python (PySide6) + a small C++ Qt plugin for the file-manager badges.
>
> GPL-3.0. Currently Fedora 44 / Plasma 6 is the tested target. Source:
> https://github.com/KSM899/gdrive-mgr
>
> Honest about the limits in the README — bisync is upstream-beta so conflicts happen; per-file pin uses 60s polling for cloud changes (no webhook).

---

## r/selfhosted

**Title:**
> gdrive-mgr — desktop Google Drive client for KDE with file-explorer integration (open-source, rclone-based)

**Body:**

> If you'd rather not pay for Insync but still want a real desktop Drive experience on Linux, I just released **gdrive-mgr** — an open-source (GPL-3.0) KDE Plasma 6 Google Drive client built on rclone.
>
> Features that aren't in vanilla `rclone mount`:
>
> - "Keep always on this device" right-click on folders AND single files
> - Per-file Dolphin overlay badges (synced/syncing/error/online-only)
> - In-app share dialog (Drive REST API directly, no browser)
> - Multi-account, conflict UI, real-disk-footprint breakdown
>
> https://github.com/KSM899/gdrive-mgr
>
> v0.1.0 — feedback welcome.
