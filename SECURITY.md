# Security

## Threat model

gdrive-mgr runs entirely as the user who installed it. There is no privileged
component, no network listener, and no IPC outside the user's session. The
trust boundary is the user account itself: anything that can read your home
directory can already read your Google Drive contents and rclone token, so we
add no new attack surface beyond what rclone already exposes.

## Where secrets live

| What | Where | Owner | Mode |
|------|-------|-------|------|
| Google OAuth refresh + access token | `~/.config/rclone/rclone.conf` | rclone (not us) | rclone-managed |
| App config (account names, pin list) | `~/.config/gdrive-mgr/config.json` | gdrive-mgr | `0600` |
| Sync state snapshot | `~/.cache/gdrive-mgr/status.json` | gdrive-mgr | `0600` |
| Daemon IPC socket | `~/.cache/gdrive-mgr/daemon.sock` | gdrive-mgr | `0600` |
| Per-pin sync history (rclone bisync) | `~/.cache/rclone/bisync/` | rclone | rclone-managed |
| On-demand mount cache | `~/.cache/rclone/vfs/` | rclone | rclone-managed |
| Pinned local copies | `~/GoogleDrive-Offline/` | user | umask default |

The Google OAuth refresh token is the most sensitive secret. We never read,
log, transmit, or write it — we only request a short-lived access token
indirectly via the same `client_id` rclone uses, then make HTTPS calls to
`drive.googleapis.com`. The refresh token lives only in `~/.config/rclone/`
under rclone's exclusive control.

## OAuth client

gdrive-mgr re-uses rclone's built-in Google Drive OAuth `client_id`. Two
implications:

1. **You are sharing Google's per-client API quota with the entire rclone
   userbase.** In normal personal use, this is a non-issue. In high-volume
   sync use, you may occasionally see rate limits.
2. **The `client_id` and `client_secret` are public values** (baked into
   rclone's open-source code). This is the standard arrangement for
   desktop OAuth apps and is explicitly allowed by Google's policies; it is
   not a vulnerability.

To use your own OAuth client (recommended for power users with many files):
follow the rclone docs at <https://rclone.org/drive/#making-your-own-client-id>
and add `client_id` and `client_secret` lines to your remote in
`~/.config/rclone/rclone.conf`. gdrive-mgr picks these up automatically.

## Network surface

All outbound traffic is HTTPS to:

- `accounts.google.com` and `oauth2.googleapis.com` — OAuth (only during
  account add or token refresh)
- `www.googleapis.com` — Drive REST API (sharing operations only; sync
  uses rclone, which talks to the same endpoints)
- `*.googleusercontent.com` — file content downloads (rclone)

No inbound listener. The daemon's Unix socket is filesystem-bound and
permission-restricted to the owner.

## Subprocess safety

All subprocess invocations use **list-form argv**, never `shell=True`. This
means user-controlled strings (file paths, email addresses, remote names)
cannot inject shell metacharacters. The relevant call sites:

- `gdrive_mgr/rclone.py` — every rclone invocation
- `gdrive_mgr/systemd_units.py` — every systemctl invocation
- `gdrive_mgr/cli.py` — clipboard, xdg-open, notification helpers
- `gdrive_mgr/daemon.py` — systemctl reconciliation calls

## Path safety (Dolphin service menu)

The Dolphin right-click menu passes a path to our CLI via `Exec=… %f`.
KDE invokes via `g_spawn_async` with split args — there is no shell
interpretation. Once in the CLI:

- `pin-path`, `unpin-path`, `sync-now`, `share-link`, `share` all resolve
  the supplied path with `pathlib.Path.resolve()` (follows symlinks) and
  reject anything not inside a configured Drive mount or offline area.
- Symlink-out attacks (a symlink under your mount pointing to `/etc/`)
  would still resolve outside the mount and be rejected at the `relative_to()`
  check.

## C++ Dolphin overlay plugin

Loaded into the Dolphin process; runs with Dolphin's permissions (your user).
Reads `~/.cache/gdrive-mgr/status.json` via `QFile` and parses with
`QJsonDocument` — no eval, no exec, no shell. The plugin emits debug lines
via `qInfo()` that show paths (no token data).

If you ever uninstall, remove the plugin separately with
`sudo rm /usr/lib64/qt6/plugins/kf6/overlayicon/gdrivemgroverlay.so`.

## Reporting a vulnerability

Open a private security advisory via the GitHub repository, or email
the maintainer directly. Do not file public issues for unfixed
vulnerabilities.
