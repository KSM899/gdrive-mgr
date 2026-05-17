# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Long-running background daemon: watches pinned folders with inotify,
schedules debounced bisyncs, writes per-folder status to status.json,
and listens for control messages on a Unix socket.

The daemon is the single owner of the StatusStore — UI components only read.

Architecture:

    inotify (per pinned folder) ───┐
                                   ├──> debounced sync scheduler ──> rclone bisync
    socket commands (pin/unpin) ───┘                                    │
                                                                        ▼
                                                                  StatusStore
                                                                        │
                                                       status.json (atomic write)
                                                                        │
                                          ┌─────────────────────────────┼─────────────┐
                                          ▼                             ▼             ▼
                                       tray                          app             Dolphin overlay
                                    (polls global_state)          (Sync panel)         plugin
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from . import rclone
from .config import Account, ConfigStore, PinnedFile, PinnedFolder
from .status import STATE_DIR, StatusStore, SyncState

SOCKET_PATH = STATE_DIR / "daemon.sock"
DEBOUNCE_SECONDS = 3.0
POLL_INTERVAL_SECONDS = 60.0
FILE_DEBOUNCE_SECONDS = 2.0

log = logging.getLogger("gdrive-mgr")


class _PinHandler(FileSystemEventHandler):
    """Forwards every change under a pinned folder to the sync scheduler."""

    def __init__(self, on_change: Callable[[], None]) -> None:
        self._on_change = on_change

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.is_directory and event.event_type == "modified":
            # Directory mtime updates are noisy and rarely meaningful here.
            return
        self._on_change()


class _SyncWorker(threading.Thread):
    """One worker per pinned folder. Owns the bisync queue + status updates.

    Coalescing: any number of fast-arriving change events bump a single
    deadline; the actual sync fires once, DEBOUNCE_SECONDS after the most
    recent event. While a sync is running, further events queue exactly one
    follow-up sync.
    """

    def __init__(
        self,
        store: ConfigStore,
        status: StatusStore,
        account: Account,
        pin: PinnedFolder,
    ) -> None:
        super().__init__(daemon=True, name=f"sync:{account.remote_name}:{pin.unit_slug()}")
        self.store = store
        self.status = status
        self.account = account
        self.pin = pin
        # Every status update is published twice — once for the local copy
        # in the offline area, once for the mirror location inside the FUSE
        # mount — so badges appear in both views.
        self.offline_path = pin.local_path
        self.mount_path = str(Path(account.mount_path) / pin.remote_path)

        self._cond = threading.Condition()
        self._deadline: float | None = None
        self._queued = False
        self._stop = False

    def _publish(self, state: SyncState, message: str = "") -> None:
        self.status.set(self.offline_path, state, message)
        self.status.set(self.mount_path, state, message)

    def clear_status(self) -> None:
        self.status.remove(self.offline_path)
        self.status.remove(self.mount_path)

    def schedule(self) -> None:
        with self._cond:
            self._deadline = time.monotonic() + DEBOUNCE_SECONDS
            self._queued = True
            self._publish(SyncState.PENDING, "change detected")
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def run(self) -> None:
        # Make sure status reflects current persisted state on startup.
        if self.pin.last_sync_ts == 0:
            self._publish(SyncState.PENDING, "initial sync pending")
            self.schedule()
        else:
            init = SyncState.SYNCED if self.pin.last_sync_ok else SyncState.ERROR
            self._publish(init, self.pin.last_error)

        while True:
            with self._cond:
                while not self._stop and not self._queued:
                    self._cond.wait(timeout=POLL_INTERVAL_SECONDS)
                    if not self._queued:
                        # Periodic pull-side check
                        self._queued = True
                        self._deadline = time.monotonic()
                if self._stop:
                    return
                # Honor debounce
                while not self._stop:
                    now = time.monotonic()
                    wait = (self._deadline or now) - now
                    if wait <= 0:
                        break
                    self._cond.wait(timeout=wait)
                if self._stop:
                    return
                self._queued = False
                self._deadline = None

            self._run_one_sync()

    def _run_one_sync(self) -> None:
        self._publish(SyncState.SYNCING, "")
        try:
            ok, output = rclone.bisync(
                remote=self.account.remote_name,
                remote_path=self.pin.remote_path,
                local_path=self.pin.local_path,
                resync=self.pin.needs_resync,
            )
        except Exception as e:
            ok, output = False, str(e)

        # bisync refuses to run if either side looks suspicious (catastrophic
        # delete, missing history, etc.) — recovery is to --resync. Detect
        # those error shapes and retry once automatically; the user otherwise
        # has no way to recover except editing config to flip needs_resync.
        if not ok and _needs_auto_resync(output):
            try:
                ok, output = rclone.bisync(
                    remote=self.account.remote_name,
                    remote_path=self.pin.remote_path,
                    local_path=self.pin.local_path,
                    resync=True,
                )
            except Exception as e:
                ok, output = False, str(e)

        self.pin.last_sync_ts = time.time()
        self.pin.last_sync_ok = ok
        self.pin.last_error = "" if ok else output[-2000:]
        if ok and self.pin.needs_resync:
            self.pin.needs_resync = False
        try:
            self.store.update_pinned(self.account.remote_name, self.pin)
        except Exception:
            pass

        if ok:
            self._publish(SyncState.SYNCED, "")
        else:
            self._publish(
                SyncState.ERROR,
                self.pin.last_error.splitlines()[-1] if self.pin.last_error else "sync failed",
            )


def _needs_auto_resync(bisync_output: str) -> bool:
    """bisync error patterns that indicate '--resync' will recover."""
    out = bisync_output.lower()
    return (
        "empty current path" in out
        or "must run --resync" in out
        or "must run resync" in out
        or "cannot find prior" in out
    )


class _FileChangeFilter(FileSystemEventHandler):
    """Watchdog handler for a single file. Forwards events only when the
    affected path matches our target file (the observer is scheduled on the
    parent directory, so it sees siblings too).
    """

    def __init__(self, target_path: str, on_change: Callable[[], None]) -> None:
        self._target = target_path
        self._on_change = on_change

    def on_any_event(self, event: FileSystemEvent) -> None:
        if event.src_path == self._target or getattr(event, "dest_path", "") == self._target:
            self._on_change()


class _FileSyncWorker(threading.Thread):
    """Bidirectional sync for one pinned file.

    - Local-side change: inotify on the parent dir triggers a debounced sync
      that uploads the local copy to Drive.
    - Cloud-side change: every `poll_interval_sec` we lsjson the file on Drive
      and compare mtime/size against the last known values; if changed,
      download.
    - Both sides changed: keep the remote version, save the local one as
      `<basename>.conflict.<timestamp>` next to it.

    The worker also publishes status to BOTH the offline path (the local
    pinned location) and the mount-side path (so badges show in either view).
    """

    def __init__(
        self,
        store: ConfigStore,
        status: StatusStore,
        account: Account,
        pin: PinnedFile,
    ) -> None:
        super().__init__(daemon=True, name=f"filesync:{account.remote_name}:{pin.remote_path}")
        self.store = store
        self.status = status
        self.account = account
        self.pin = pin

        self.offline_path = pin.local_path
        self.mount_path = str(Path(account.mount_path) / pin.remote_path)

        self._cond = threading.Condition()
        self._deadline: float | None = None
        self._queued = False
        self._stop = False

    # ---- status helpers ----

    def _publish(self, state: SyncState, message: str = "") -> None:
        self.status.set(self.offline_path, state, message)
        self.status.set(self.mount_path, state, message)

    def clear_status(self) -> None:
        self.status.remove(self.offline_path)
        self.status.remove(self.mount_path)

    # ---- scheduling ----

    def schedule(self) -> None:
        with self._cond:
            self._deadline = time.monotonic() + FILE_DEBOUNCE_SECONDS
            self._queued = True
            self._publish(SyncState.PENDING, "change detected")
            self._cond.notify_all()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify_all()

    def run(self) -> None:
        if self.pin.last_sync_ts == 0:
            self._publish(SyncState.PENDING, "initial sync pending")
            self.schedule()
        else:
            init = SyncState.SYNCED if self.pin.last_sync_ok else SyncState.ERROR
            self._publish(init, self.pin.last_error)

        while True:
            with self._cond:
                while not self._stop and not self._queued:
                    self._cond.wait(timeout=self.pin.poll_interval_sec)
                    if not self._queued:
                        # Periodic cloud-side check
                        self._queued = True
                        self._deadline = time.monotonic()
                if self._stop:
                    return
                while not self._stop:
                    now = time.monotonic()
                    wait = (self._deadline or now) - now
                    if wait <= 0:
                        break
                    self._cond.wait(timeout=wait)
                if self._stop:
                    return
                self._queued = False
                self._deadline = None

            self._run_one_sync()

    # ---- the core sync logic ----

    def _run_one_sync(self) -> None:
        self._publish(SyncState.SYNCING, "")

        local_path = Path(self.offline_path)
        local_exists = local_path.exists()
        local_mtime = local_path.stat().st_mtime if local_exists else 0.0

        # Compare against last known state
        remote_entry = rclone.stat_file(self.account.remote_name, self.pin.remote_path)

        local_changed = local_exists and local_mtime > self.pin.last_known_local_mtime + 0.5
        remote_changed = remote_entry is not None and (
            remote_entry.modified_iso != self.pin.last_known_remote_modtime
            or remote_entry.size != self.pin.last_known_remote_size
        )
        remote_missing = remote_entry is None and self.pin.last_known_remote_modtime != ""

        ok = True
        err = ""
        action = "noop"

        if local_changed and remote_changed:
            action = "conflict"
            backup = str(local_path) + f".conflict.{int(time.time())}"
            try:
                import shutil
                shutil.copy2(self.offline_path, backup)
            except Exception as e:
                ok, err = False, f"backup failed: {e}"
            if ok:
                ok, output = rclone.copyto(
                    f"{self.account.remote_name}:{self.pin.remote_path}",
                    self.offline_path,
                )
                if not ok:
                    err = output[-2000:]
        elif local_changed:
            action = "upload"
            ok, output = rclone.copyto(
                self.offline_path,
                f"{self.account.remote_name}:{self.pin.remote_path}",
            )
            if not ok:
                err = output[-2000:]
        elif remote_changed or (remote_entry and not local_exists):
            action = "download"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            ok, output = rclone.copyto(
                f"{self.account.remote_name}:{self.pin.remote_path}",
                self.offline_path,
            )
            if not ok:
                err = output[-2000:]
        elif remote_missing:
            # Remote file was deleted. Don't auto-delete locally; surface as
            # error so the user can decide.
            action = "remote-gone"
            ok, err = False, "remote file no longer exists"

        # Update last-known state after a successful sync
        if ok and action != "noop":
            try:
                latest = rclone.stat_file(self.account.remote_name, self.pin.remote_path)
                if latest is not None:
                    self.pin.last_known_remote_modtime = latest.modified_iso
                    self.pin.last_known_remote_size = latest.size
                if local_path.exists():
                    self.pin.last_known_local_mtime = local_path.stat().st_mtime
            except Exception:
                pass

        self.pin.last_sync_ts = time.time()
        self.pin.last_sync_ok = ok
        self.pin.last_error = "" if ok else err
        try:
            self.store.update_pinned_file(self.account.remote_name, self.pin)
        except Exception:
            pass

        if ok:
            self._publish(SyncState.SYNCED, "" if action == "noop" else action)
        else:
            self._publish(SyncState.ERROR, err.splitlines()[-1] if err else "sync failed")


class Daemon:
    """Top-level orchestrator. One observer for all pinned paths; one worker
    per pin; one Unix socket for control."""

    def __init__(self) -> None:
        self.store = ConfigStore()
        self.status = StatusStore()
        self.observer = Observer()
        self.workers: dict[tuple[str, str], _SyncWorker] = {}
        # Keyed identically (remote_name, remote_path) but in a separate dict
        # because file pins and folder pins are managed by different workers
        # and we never collide on key (a path is either a file or a dir).
        self.file_workers: dict[tuple[str, str], _FileSyncWorker] = {}
        self._sock: socket.socket | None = None
        self._stop = threading.Event()

    # ---- lifecycle ----

    def start(self) -> None:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        log.info("daemon starting; %d account(s) in config", len(self.store.config.accounts))
        self._cleanup_orphan_timers()
        self._populate_from_config()
        self.observer.start()
        self._start_socket()

        threading.Thread(target=self._reconcile_loop, daemon=True).start()

        try:
            while not self._stop.is_set():
                self._stop.wait(timeout=1.0)
        finally:
            self.stop()

    def stop(self) -> None:
        self._stop.set()
        for w in self.workers.values():
            w.stop()
        for w in self.file_workers.values():
            w.stop()
        try:
            self.observer.stop()
            self.observer.join(timeout=5)
        except Exception:
            pass
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                if SOCKET_PATH.exists():
                    SOCKET_PATH.unlink(missing_ok=True)

    # ---- workers ----

    def _populate_from_config(self) -> None:
        seen: set[tuple[str, str]] = set()
        seen_files: set[tuple[str, str]] = set()
        for acc in self.store.config.accounts:
            # Mark each account's FUSE mount root as online-only so unpinned
            # items under it inherit the cloud badge. Pinned descendants
            # override via longest-prefix match in the plugin.
            self.status.set(acc.mount_path, SyncState.ONLINE_ONLY, "")
            for pin in acc.pinned:
                key = (acc.remote_name, pin.remote_path)
                seen.add(key)
                if key in self.workers:
                    continue
                self._add_worker(acc, pin)
            for fpin in acc.pinned_files:
                key = (acc.remote_name, fpin.remote_path)
                seen_files.add(key)
                if key in self.file_workers:
                    continue
                self._add_file_worker(acc, fpin)
        # Drop workers for pins that have been removed
        for key in list(self.workers.keys()):
            if key not in seen:
                self._remove_worker(*key)
        for key in list(self.file_workers.keys()):
            if key not in seen_files:
                self._remove_file_worker(*key)

    def _add_worker(self, account: Account, pin: PinnedFolder) -> None:
        log.info("adding folder worker: %s:%s", account.remote_name, pin.remote_path)
        Path(pin.local_path).mkdir(parents=True, exist_ok=True)
        worker = _SyncWorker(self.store, self.status, account, pin)
        self.workers[(account.remote_name, pin.remote_path)] = worker
        handler = _PinHandler(worker.schedule)
        try:
            self.observer.schedule(handler, pin.local_path, recursive=True)
        except Exception as e:
            log.warning("watch failed for %s: %s", pin.local_path, e)
            self.status.set(pin.local_path, SyncState.ERROR, f"watch failed: {e}")
        worker.start()

    def _remove_worker(self, remote_name: str, remote_path: str) -> None:
        worker = self.workers.pop((remote_name, remote_path), None)
        if worker is not None:
            worker.stop()
            worker.clear_status()

    def _add_file_worker(self, account: Account, pin: PinnedFile) -> None:
        log.info("adding file worker: %s:%s", account.remote_name, pin.remote_path)
        local_dir = Path(pin.local_path).parent
        local_dir.mkdir(parents=True, exist_ok=True)
        worker = _FileSyncWorker(self.store, self.status, account, pin)
        self.file_workers[(account.remote_name, pin.remote_path)] = worker
        handler = _FileChangeFilter(pin.local_path, worker.schedule)
        try:
            self.observer.schedule(handler, str(local_dir), recursive=False)
        except Exception as e:
            log.warning("file watch failed for %s: %s", pin.local_path, e)
            self.status.set(pin.local_path, SyncState.ERROR, f"watch failed: {e}")
        worker.start()

    def _remove_file_worker(self, remote_name: str, remote_path: str) -> None:
        worker = self.file_workers.pop((remote_name, remote_path), None)
        if worker is not None:
            worker.stop()
            worker.clear_status()

    def _cleanup_orphan_timers(self) -> None:
        """Disable any `gdrive-pin@*.timer` whose remote+slug doesn't match an
        actual pin in the current config. Prevents orphan timers (e.g. from a
        previous unpin that failed mid-way) from firing every 15 minutes."""
        try:
            proc = subprocess.run(
                ["systemctl", "--user", "list-unit-files", "gdrive-pin@*", "--no-pager", "--no-legend"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception as e:
            log.warning("could not list pin timers: %s", e)
            return

        wanted: set[str] = set()
        for acc in self.store.config.accounts:
            for pin in acc.pinned:
                wanted.add(f"{acc.remote_name}--{pin.unit_slug()}")

        for line in proc.stdout.splitlines():
            unit = line.split()[0] if line.strip() else ""
            if not unit.startswith("gdrive-pin@") or not unit.endswith(".timer"):
                continue
            instance = unit[len("gdrive-pin@"):-len(".timer")]
            if not instance or instance in wanted:
                continue
            # Only disable if the unit is actually enabled — list-unit-files
            # shows everything that has ever been registered.
            check = subprocess.run(
                ["systemctl", "--user", "is-enabled", unit],
                capture_output=True, text=True, timeout=5,
            )
            if check.stdout.strip() != "enabled":
                continue
            log.info("disabling orphan pin timer: %s", unit)
            subprocess.run(
                ["systemctl", "--user", "disable", "--now", unit],
                capture_output=True, timeout=10,
            )
            subprocess.run(
                ["systemctl", "--user", "reset-failed", f"gdrive-pin@{instance}.service"],
                capture_output=True, timeout=5,
            )

    def _reconcile_loop(self) -> None:
        while not self._stop.is_set():
            self._stop.wait(timeout=30.0)
            if self._stop.is_set():
                return
            try:
                # Reload in-place so existing workers' self.store stays
                # consistent with the daemon's view.
                self.store.reload()
                self._populate_from_config()
            except Exception:
                continue

    # ---- control socket ----

    def _start_socket(self) -> None:
        SOCKET_PATH.unlink(missing_ok=True)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(str(SOCKET_PATH))
        sock.listen(8)
        os.chmod(SOCKET_PATH, 0o600)
        self._sock = sock
        threading.Thread(target=self._accept_loop, daemon=True).start()

    def _accept_loop(self) -> None:
        assert self._sock is not None
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle_conn, args=(conn,), daemon=True).start()

    def _handle_conn(self, conn: socket.socket) -> None:
        try:
            data = conn.recv(8192).decode("utf-8", errors="replace").strip()
            if not data:
                return
            try:
                req = json.loads(data)
            except json.JSONDecodeError:
                conn.sendall(b'{"ok":false,"error":"bad json"}\n')
                return
            response = self._handle_cmd(req)
            conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
        finally:
            conn.close()

    def _handle_cmd(self, req: dict) -> dict:
        cmd = req.get("cmd")
        if cmd == "reload":
            # Reload in-place so existing workers (which hold a reference to
            # self.store) keep seeing fresh data and don't clobber on save.
            self.store.reload()
            self._populate_from_config()
            return {"ok": True}
        if cmd == "sync-now":
            remote = req.get("remote")
            path = req.get("remote_path")
            worker = self.workers.get((remote, path)) or self.file_workers.get((remote, path))
            if worker is None:
                return {"ok": False, "error": "unknown pin"}
            worker.schedule()
            return {"ok": True}
        if cmd == "status":
            return {
                "ok": True,
                "global": self.status.global_state().value,
                "entries": [e.to_dict() for e in self.status.all()],
            }
        return {"ok": False, "error": f"unknown cmd: {cmd}"}


def send_cmd(req: dict, timeout: float = 2.0) -> dict:
    """Convenience: send one JSON request to the daemon and parse the reply."""
    if not SOCKET_PATH.exists():
        return {"ok": False, "error": "daemon not running"}
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(SOCKET_PATH))
        s.sendall((json.dumps(req) + "\n").encode("utf-8"))
        buf = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            buf += chunk
            if b"\n" in chunk:
                break
        return json.loads(buf.decode("utf-8").strip() or "{}")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    finally:
        s.close()


def main() -> int:
    # systemd captures stderr into the journal via StandardError=journal in
    # the unit file, so a simple StreamHandler is all we need.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s: %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    d = Daemon()
    try:
        d.start()
    except KeyboardInterrupt:
        d.stop()
    except Exception:
        log.exception("daemon crashed")
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
