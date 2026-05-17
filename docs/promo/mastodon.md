# Mastodon (Fediverse) post

The Linux/KDE communities are particularly active on:

- **fosstodon.org** (general FOSS)
- **floss.social** (general FOSS)
- **mastodon.social** with KDE hashtags

The official **@kde@floss.social** account often boosts release announcements
from community apps — mention them and they may share.

---

**Post (485 chars, fits in 500-char limit):**

> Just released **gdrive-mgr** 0.1.0 — a Google Drive client for KDE Plasma 6.
>
> ✓ Files-on-demand mount (rclone-based)
> ✓ Right-click in Dolphin → "Keep always on this device" (folders AND single files)
> ✓ Per-file Dolphin overlay badges via a C++ KOverlayIconPlugin
> ✓ Native Qt share dialog (no browser hop)
> ✓ Multi-account, conflict UI, real disk-usage breakdown
>
> GPL-3.0, Python + a tiny C++ plugin.
>
> https://github.com/KSM899/gdrive-mgr
>
> #KDE #Plasma #Linux #OpenSource #GoogleDrive

---

**Follow-up thread (post these as replies to your own first toot):**

**Reply 1 — why:**

> Built this because nothing on Linux gave me the same on-demand-with-pinning experience as Google Drive Desktop on macOS/Windows.
>
> KIO GDrive is buggy on Plasma 6, Insync is paid, raw rclone has no GUI integration. So I wrote what I wanted.

**Reply 2 — the share thing:**

> The detail I'm most proud of: the Share dialog. Hits Google Drive's REST API directly, re-uses rclone's already-authorized OAuth token. No browser hop, no second consent flow.
>
> Add an email + role, click Share, done.

**Reply 3 — call to action:**

> If you're on KDE and want to try it: https://github.com/KSM899/gdrive-mgr
>
> Currently tested on Fedora 44 / Plasma 6.4 — looking for testers on other distros (Arch, openSUSE, KDE Neon).
>
> Bug reports and packaging contributions welcome.
