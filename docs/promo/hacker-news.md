# Hacker News — Show HN

URL: https://news.ycombinator.com/submit

**Best posting time:** Tuesday or Wednesday, 8–10am US Eastern (the
morning queue gets the most upvotes-per-minute, which is what HN's
algorithm rewards).

**Title rules:** must start with "Show HN: ". Keep it under 80 chars.
No emoji. Don't repeat the URL in the title.

---

**Title:**
> Show HN: gdrive-mgr – KDE-native Google Drive client with on-demand mount

**URL field:** `https://github.com/KSM899/gdrive-mgr`

**Text field:** (Show HN comments are limited to a few short paragraphs)

> I built this because nothing on Linux gives the same on-demand-with-pinning experience Google Drive Desktop has on Windows/macOS. KIO GDrive is buggy on Plasma 6, Insync is paid, and raw rclone has no GUI integration.
>
> Architecture: Python + PySide6 for the GUI, rclone for the actual sync (mount + bisync for folders, copyto + polling for single files), a 200-line C++ Qt plugin (KOverlayIconPlugin) for per-file Dolphin overlay badges, and systemd user units for lifecycle.
>
> Things I'm proud of: the in-app share dialog talks to the Drive REST API directly using rclone's stored OAuth token — no browser hop and no separate consent flow. The per-file pin path uses inotify for local edits and a 60-second poll for cloud-side changes; conflicts surface as `.conflict.<ts>` files with a dedicated UI tab.
>
> Things that aren't there yet: Shared Drives, Drive change-notification webhooks (so cloud-edit pickup is poll-based), and Flathub packaging (the systemd integration fights the sandbox). The README is honest about the limits.
>
> GPL-3.0. Tested on Fedora 44 / Plasma 6.4. Would love feedback from people on other distros / KDE versions.

**Tips:**

- Engage with every comment, even hostile ones. HN rewards authors who reply.
- Don't ask for upvotes anywhere — instant flag.
- If the post stalls (under 5 points after an hour), don't repost the same day. Wait 48 hours and try a different angle.
