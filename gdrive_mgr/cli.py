# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""CLI entrypoints invoked by systemd units, Dolphin right-click, and humans.

Use `python3 -m gdrive_mgr.cli <command> <args>`. The Dolphin service menu
calls `pin-path` / `unpin-path` with an absolute filesystem path; we figure
out which account it belongs to and update the pin list.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import rclone
from .config import Account, ConfigStore, PinnedFile, PinnedFolder
from .systemd_units import (
    disable_pin,
    enable_pin,
    ensure_template_units,
    parse_pin_instance,
)


def _cmd_bisync_instance(args: argparse.Namespace) -> int:
    remote, slug = parse_pin_instance(args.instance)
    store = ConfigStore()
    acc = store.account(remote)
    if acc is None:
        print(f"[bisync] no such account: {remote}", file=sys.stderr)
        return 2
    pin = next((p for p in acc.pinned if p.unit_slug() == slug), None)
    if pin is None:
        print(f"[bisync] no pin {slug!r} for {remote}", file=sys.stderr)
        return 2

    ok, output = rclone.bisync(
        remote=remote,
        remote_path=pin.remote_path,
        local_path=pin.local_path,
        resync=pin.needs_resync,
    )
    pin.last_sync_ts = time.time()
    pin.last_sync_ok = ok
    pin.last_error = "" if ok else output[-2000:]
    if ok and pin.needs_resync:
        pin.needs_resync = False
    store.update_pinned(remote, pin)
    if not ok:
        print(output, file=sys.stderr)
    return 0 if ok else 1


def _resolve_in_mount(store: ConfigStore, target: Path) -> tuple[Account, str] | None:
    """Given an absolute path, return (account, remote-relative-path) if the
    path is inside one of the configured FUSE mount points. Used by 'pin-path'
    when the user right-clicks a folder in the on-demand view."""
    for acc in store.config.accounts:
        mount = Path(acc.mount_path).resolve()
        try:
            rel = target.resolve().relative_to(mount)
        except ValueError:
            continue
        if str(rel) == ".":
            return None
        return acc, str(rel)
    return None


def _resolve_in_offline(store: ConfigStore, target: Path) -> tuple[Account, PinnedFolder] | None:
    """Given an absolute path, return (account, pin) if the path is inside any
    pinned-folder root. Used by 'unpin-path'."""
    p = target.resolve()
    for acc in store.config.accounts:
        for pin in acc.pinned:
            root = Path(pin.local_path).resolve()
            try:
                p.relative_to(root)
            except ValueError:
                continue
            return acc, pin
    return None


def _resolve_pinned_file(store: ConfigStore, target: Path) -> tuple[Account, PinnedFile] | None:
    """Find a pinned-file record by either the local copy path or the FUSE
    mount-side path."""
    p = str(target.resolve())
    for acc in store.config.accounts:
        for fpin in acc.pinned_files:
            mount_side = str(Path(acc.mount_path) / fpin.remote_path)
            if p == fpin.local_path or p == mount_side:
                return acc, fpin
    return None


def _cmd_pin_path(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if not target.exists():
        print(f"path does not exist: {target}", file=sys.stderr)
        return 2

    store = ConfigStore()
    resolved = _resolve_in_mount(store, target)
    if resolved is None:
        print(
            f"{target} is not inside any configured Google Drive mount.\n"
            f"Mount points: {[a.mount_path for a in store.config.accounts]}",
            file=sys.stderr,
        )
        return 3
    account, remote_path = resolved

    if target.is_dir():
        return _pin_folder(store, account, remote_path)
    return _pin_file(store, account, remote_path)


def _pin_folder(store: ConfigStore, account: Account, remote_path: str) -> int:
    if any(p.remote_path == remote_path for p in account.pinned):
        print(f"already pinned: {account.remote_name}:{remote_path}")
        return 0

    local_path = str(Path(store.config.offline_root) / account.remote_name / remote_path)
    Path(local_path).mkdir(parents=True, exist_ok=True)
    pin = PinnedFolder(remote_path=remote_path, local_path=local_path, needs_resync=True)
    store.add_pinned(account.remote_name, pin)

    ensure_template_units()
    try:
        enable_pin(account.remote_name, pin)
    except Exception as e:
        print(f"warning: could not enable systemd timer: {e}", file=sys.stderr)

    try:
        from .daemon import send_cmd
        send_cmd({"cmd": "reload"})
    except Exception:
        pass

    print(f"pinned folder {account.remote_name}:{remote_path}  →  {local_path}")
    return 0


def _pin_file(store: ConfigStore, account: Account, remote_path: str) -> int:
    if any(p.remote_path == remote_path for p in account.pinned_files):
        print(f"already pinned: {account.remote_name}:{remote_path}")
        return 0

    local_path = str(Path(store.config.offline_root) / account.remote_name / remote_path)
    Path(local_path).parent.mkdir(parents=True, exist_ok=True)
    pin = PinnedFile(remote_path=remote_path, local_path=local_path)
    store.add_pinned_file(account.remote_name, pin)

    ensure_template_units()  # for the daemon unit (no per-file timer needed)

    try:
        from .daemon import send_cmd
        send_cmd({"cmd": "reload"})
    except Exception:
        pass

    print(f"pinned file {account.remote_name}:{remote_path}  →  {local_path}")
    return 0


def _cmd_unpin_path(args: argparse.Namespace) -> int:
    target = Path(args.path)
    store = ConfigStore()

    # First: is this a pinned single file? (Match by either local copy or
    # mount-side path.)
    file_resolved = _resolve_pinned_file(store, target)
    if file_resolved is not None:
        account, fpin = file_resolved
        if args.delete_local:
            try:
                Path(fpin.local_path).unlink(missing_ok=True)
            except Exception as e:
                print(f"warning: could not delete local copy: {e}", file=sys.stderr)
        store.remove_pinned_file(account.remote_name, fpin.remote_path)
        try:
            from .daemon import send_cmd
            send_cmd({"cmd": "reload"})
        except Exception:
            pass
        print(f"unpinned file {account.remote_name}:{fpin.remote_path}")
        return 0

    # Otherwise treat as folder unpin.
    resolved = _resolve_in_offline(store, target)
    if resolved is None:
        mt = _resolve_in_mount(store, target)
        if mt is None:
            print(f"{target} is not inside any managed location.", file=sys.stderr)
            return 3
        account, remote_path = mt
        pin = next((p for p in account.pinned if p.remote_path == remote_path), None)
        if pin is None:
            print(f"{remote_path!r} is not pinned.", file=sys.stderr)
            return 0
    else:
        account, pin = resolved

    try:
        disable_pin(account.remote_name, pin)
    except Exception:
        pass

    if args.delete_local:
        import shutil
        try:
            shutil.rmtree(pin.local_path)
        except Exception as e:
            print(f"warning: could not delete local copy: {e}", file=sys.stderr)

    store.remove_pinned(account.remote_name, pin.remote_path)

    try:
        from .daemon import send_cmd
        send_cmd({"cmd": "reload"})
    except Exception:
        pass

    print(f"unpinned folder {account.remote_name}:{pin.remote_path}")
    return 0


def _cmd_daemon(_args: argparse.Namespace) -> int:
    from .daemon import main as daemon_main
    return daemon_main()


def _to_clipboard(text: str) -> bool:
    """Copy `text` to the system clipboard. Tries Wayland first, then X11,
    then KDE Klipper via D-Bus. Returns True on success."""
    import shutil
    import subprocess

    candidates: list[list[str]] = []
    if shutil.which("wl-copy"):
        candidates.append(["wl-copy"])
    if shutil.which("xclip"):
        candidates.append(["xclip", "-selection", "clipboard"])
    if shutil.which("xsel"):
        candidates.append(["xsel", "--clipboard", "--input"])

    for cmd in candidates:
        try:
            subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
            return True
        except Exception:
            continue

    for qd in ("qdbus6", "qdbus"):
        if not shutil.which(qd):
            continue
        try:
            subprocess.run(
                [qd, "org.kde.klipper", "/klipper", "setClipboardContents", text],
                check=True, timeout=5,
            )
            return True
        except Exception:
            continue
    return False


def _notify(title: str, body: str) -> None:
    import shutil
    import subprocess
    if shutil.which("notify-send"):
        try:
            subprocess.run(
                ["notify-send", "-i", "folder-cloud", title, body],
                check=False, timeout=5,
            )
            return
        except Exception:
            pass
    if shutil.which("kdialog"):
        try:
            subprocess.run(
                ["kdialog", "--passivepopup", f"{title}\n{body}", "5"],
                check=False, timeout=5,
            )
        except Exception:
            pass


def _resolve_for_share(store: ConfigStore, target: Path) -> tuple[str, str] | None:
    """Find which (remote, remote_path) a Dolphin-clicked path corresponds to.
    Accepts paths under the FUSE mount or under the offline area."""
    p = target.resolve()
    for acc in store.config.accounts:
        mount = Path(acc.mount_path).resolve()
        try:
            rel = p.relative_to(mount)
        except ValueError:
            pass
        else:
            return acc.remote_name, str(rel) if str(rel) != "." else ""
        offline_root = (Path(store.config.offline_root) / acc.remote_name).resolve()
        try:
            rel = p.relative_to(offline_root)
        except ValueError:
            continue
        return acc.remote_name, str(rel) if str(rel) != "." else ""
    return None


def _cmd_share_link(args: argparse.Namespace) -> int:
    target = Path(args.path)
    store = ConfigStore()
    resolved = _resolve_for_share(store, target)
    if resolved is None:
        _notify("Share link failed", f"{target} is not inside a managed Drive location.")
        print(f"{target} is not inside any managed location.", file=sys.stderr)
        return 3
    remote, remote_path = resolved
    try:
        url = rclone.share_link(remote, remote_path)
    except rclone.RcloneError as e:
        _notify("Share link failed", str(e).splitlines()[0])
        print(str(e), file=sys.stderr)
        return 1

    label = target.name or remote
    if _to_clipboard(url):
        _notify("Drive link copied", f"{label}\n{url}")
        print(url)
    else:
        _notify("Drive link ready", f"{label}\n{url}\n\n(No clipboard tool found; URL printed to stdout.)")
        print(url)
    return 0


def _cmd_share_open(args: argparse.Namespace) -> int:
    """Launch the native Qt share dialog (in-process, modal until closed).

    Runs a short-lived QApplication just for this dialog; we exit when the
    dialog closes. This is invoked by Dolphin's right-click menu, so it
    lives only as long as the user is interacting with it.
    """
    target = Path(args.path)
    store = ConfigStore()
    resolved = _resolve_for_share(store, target)
    if resolved is None:
        _notify("Share failed", f"{target} is not inside a managed Drive location.")
        print(f"{target} is not inside any managed location.", file=sys.stderr)
        return 3
    remote, remote_path = resolved
    drive_id = rclone.file_id(remote, remote_path)
    if not drive_id:
        _notify(
            "Share failed",
            f"Could not find {target.name} in Drive yet — wait for it to sync, then try again.",
        )
        print(f"no Drive ID for {remote}:{remote_path}", file=sys.stderr)
        return 4

    # Import Qt lazily so the other CLI commands (no GUI needed) stay fast.
    from PySide6.QtWidgets import QApplication
    from .ui.share_dialog import ShareDialog

    app = QApplication.instance() or QApplication(sys.argv)
    dialog = ShareDialog(remote, drive_id, remote_path or target.name)
    dialog.exec()
    return 0


def _cmd_sync_now(args: argparse.Namespace) -> int:
    target = Path(args.path)
    store = ConfigStore()

    # File pin first
    file_resolved = _resolve_pinned_file(store, target)
    if file_resolved is not None:
        account, fpin = file_resolved
        from .daemon import send_cmd
        resp = send_cmd({"cmd": "sync-now", "remote": account.remote_name, "remote_path": fpin.remote_path})
        if not resp.get("ok"):
            print(f"daemon: {resp.get('error', 'unknown')}", file=sys.stderr)
            return 1
        print(f"sync queued for file {account.remote_name}:{fpin.remote_path}")
        return 0

    resolved = _resolve_in_offline(store, target)
    if resolved is None:
        in_mount = _resolve_in_mount(store, target)
        if in_mount is None:
            print(f"{target} is not inside any managed location.", file=sys.stderr)
            return 3
        print(
            f"{target} is in the on-demand mount, not pinned. "
            "Use 'Keep always on this device' to pin it first.",
            file=sys.stderr,
        )
        return 4
    account, pin = resolved
    from .daemon import send_cmd
    resp = send_cmd({"cmd": "sync-now", "remote": account.remote_name, "remote_path": pin.remote_path})
    if not resp.get("ok"):
        print(f"daemon: {resp.get('error', 'unknown')}", file=sys.stderr)
        return 1
    print(f"sync queued for {account.remote_name}:{pin.remote_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m gdrive_mgr.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_bi = sub.add_parser("bisync-instance", help="Run bisync for a pin instance name.")
    p_bi.add_argument("instance", help="systemd template instance, e.g. gdrive--Work")
    p_bi.set_defaults(func=_cmd_bisync_instance)

    p_pin = sub.add_parser("pin-path", help="Pin the folder at PATH for offline use.")
    p_pin.add_argument("path", help="Absolute path to a folder inside a Drive mount.")
    p_pin.set_defaults(func=_cmd_pin_path)

    p_unpin = sub.add_parser("unpin-path", help="Unpin the folder at PATH.")
    p_unpin.add_argument("path", help="Absolute path inside a pinned folder or mount.")
    p_unpin.add_argument(
        "--delete-local",
        action="store_true",
        help="Also delete the local synced copy on disk.",
    )
    p_unpin.set_defaults(func=_cmd_unpin_path)

    p_daemon = sub.add_parser("daemon", help="Run the background sync daemon.")
    p_daemon.set_defaults(func=_cmd_daemon)

    p_sync = sub.add_parser("sync-now", help="Trigger an immediate sync for the pin containing PATH.")
    p_sync.add_argument("path", help="Absolute path inside a pinned folder.")
    p_sync.set_defaults(func=_cmd_sync_now)

    p_link = sub.add_parser("share-link", help="Copy a 'anyone with link' URL for PATH to the clipboard.")
    p_link.add_argument("path", help="Absolute path inside the mount or offline area.")
    p_link.set_defaults(func=_cmd_share_link)

    p_share = sub.add_parser("share", help="Open the Drive sharing dialog for PATH in a browser.")
    p_share.add_argument("path", help="Absolute path inside the mount or offline area.")
    p_share.set_defaults(func=_cmd_share_open)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
