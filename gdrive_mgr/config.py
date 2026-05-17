# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Persistent app config: accounts and pinned (offline) folders.

Stored at ~/.config/gdrive-mgr/config.json. Schema is intentionally
flat and forward-tolerant: unknown keys are preserved on round-trip.
"""

from __future__ import annotations

import fcntl
import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Callable

CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "gdrive-mgr"
CONFIG_PATH = CONFIG_DIR / "config.json"


@dataclass
class PinnedFolder:
    remote_path: str           # path within the rclone remote, e.g. "Work/Projects"
    local_path: str            # absolute local path where bisync copy lives
    sync_interval_min: int = 15
    last_sync_ts: float = 0.0
    last_sync_ok: bool = True
    last_error: str = ""
    needs_resync: bool = True  # bisync requires --resync on first run

    def unit_slug(self) -> str:
        safe = self.remote_path.replace("/", "-").replace(" ", "_")
        return safe.strip("-") or "root"


@dataclass
class PinnedFile:
    """A single file kept always-on-device. Synced via rclone copyto in both
    directions, with cloud-side change detection by modtime/size polling."""
    remote_path: str
    local_path: str
    poll_interval_sec: int = 60
    last_sync_ts: float = 0.0
    last_sync_ok: bool = True
    last_error: str = ""
    last_known_remote_modtime: str = ""   # ISO8601 from rclone lsjson
    last_known_remote_size: int = -1
    last_known_local_mtime: float = 0.0   # os.stat.st_mtime when we last reconciled


@dataclass
class Account:
    remote_name: str                       # rclone remote name (e.g. "gdrive-personal")
    display_name: str                      # human label shown in UI
    mount_path: str                        # absolute path where the FUSE mount lives
    cache_size_gb: int = 10
    cache_max_age_hours: int = 24
    pinned: list[PinnedFolder] = field(default_factory=list)
    pinned_files: list[PinnedFile] = field(default_factory=list)
    mount_enabled: bool = True             # whether we want it mounted on login

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Account":
        pinned = [PinnedFolder(**p) for p in d.get("pinned", [])]
        pinned_files = [PinnedFile(**p) for p in d.get("pinned_files", [])]
        d = {**d, "pinned": pinned, "pinned_files": pinned_files}
        return cls(**d)


@dataclass
class AppConfig:
    accounts: list[Account] = field(default_factory=list)
    offline_root: str = str(Path.home() / "GoogleDrive-Offline")
    schema_version: int = 1

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        accounts = [Account.from_dict(a) for a in d.get("accounts", [])]
        return cls(
            accounts=accounts,
            offline_root=d.get("offline_root", str(Path.home() / "GoogleDrive-Offline")),
            schema_version=d.get("schema_version", 1),
        )


class ConfigStore:
    """Load/save wrapper around AppConfig.

    Concurrency model: every mutation re-reads the config from disk under an
    advisory file lock (fcntl.flock) before applying the change, then writes
    atomically. This means it's safe for the daemon, GUI, and CLI subprocesses
    to all hold ConfigStore instances and mutate concurrently — a stale
    in-memory snapshot can't clobber another writer's just-saved data.
    """

    def __init__(self, path: Path = CONFIG_PATH) -> None:
        self.path = path
        self._lock = RLock()
        self._config = self._load()

    def _load(self) -> AppConfig:
        if not self.path.exists():
            return AppConfig()
        try:
            data = json.loads(self.path.read_text())
            return AppConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError, KeyError) as e:
            backup = self.path.with_suffix(".json.broken")
            self.path.rename(backup)
            print(f"[config] corrupt config moved to {backup}: {e}")
            return AppConfig()

    @contextmanager
    def _exclusive(self):
        """Hold a cross-process fcntl lock on a sidecar lock file and reload
        the in-memory config from disk under it. Use for any read-modify-write
        sequence so two writers can't clobber each other."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(".lock")
        with self._lock:
            with open(lock_path, "w") as lockf:
                fcntl.flock(lockf, fcntl.LOCK_EX)
                try:
                    self._config = self._load()
                    yield
                finally:
                    pass  # lock released on file close

    def reload(self) -> None:
        """Re-read config from disk. Cheap; use this when an external writer
        (e.g. the CLI) has saved and we want to see the new state."""
        with self._lock:
            self._config = self._load()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(asdict(self._config), indent=2))
            # Owner-only: the config doesn't currently carry secrets, but it
            # does enumerate local paths and remote names — restrict it
            # anyway so we don't leak across user boundaries on shared hosts.
            os.chmod(tmp, 0o600)
            tmp.replace(self.path)

    @property
    def config(self) -> AppConfig:
        return self._config

    def account(self, remote_name: str) -> Account | None:
        for a in self._config.accounts:
            if a.remote_name == remote_name:
                return a
        return None

    # ---- mutations: all read-modify-write happens under _exclusive() ----

    def add_account(self, account: Account) -> None:
        with self._exclusive():
            if self.account(account.remote_name):
                raise ValueError(f"account {account.remote_name!r} already exists")
            self._config.accounts.append(account)
            self.save()

    def remove_account(self, remote_name: str) -> None:
        with self._exclusive():
            self._config.accounts = [
                a for a in self._config.accounts if a.remote_name != remote_name
            ]
            self.save()

    def add_pinned(self, remote_name: str, pin: PinnedFolder) -> None:
        with self._exclusive():
            acc = self.account(remote_name)
            if acc is None:
                raise KeyError(remote_name)
            if any(p.remote_path == pin.remote_path for p in acc.pinned):
                return
            acc.pinned.append(pin)
            self.save()

    def remove_pinned(self, remote_name: str, remote_path: str) -> None:
        with self._exclusive():
            acc = self.account(remote_name)
            if acc is None:
                return
            acc.pinned = [p for p in acc.pinned if p.remote_path != remote_path]
            self.save()

    def update_pinned(self, remote_name: str, pin: PinnedFolder) -> None:
        with self._exclusive():
            acc = self.account(remote_name)
            if acc is None:
                return
            for i, p in enumerate(acc.pinned):
                if p.remote_path == pin.remote_path:
                    acc.pinned[i] = pin
                    break
            self.save()

    # ---- per-file pinning ----

    def add_pinned_file(self, remote_name: str, pin: PinnedFile) -> None:
        with self._exclusive():
            acc = self.account(remote_name)
            if acc is None:
                raise KeyError(remote_name)
            if any(p.remote_path == pin.remote_path for p in acc.pinned_files):
                return
            acc.pinned_files.append(pin)
            self.save()

    def remove_pinned_file(self, remote_name: str, remote_path: str) -> None:
        with self._exclusive():
            acc = self.account(remote_name)
            if acc is None:
                return
            acc.pinned_files = [
                p for p in acc.pinned_files if p.remote_path != remote_path
            ]
            self.save()

    def update_pinned_file(self, remote_name: str, pin: PinnedFile) -> None:
        with self._exclusive():
            acc = self.account(remote_name)
            if acc is None:
                return
            for i, p in enumerate(acc.pinned_files):
                if p.remote_path == pin.remote_path:
                    acc.pinned_files[i] = pin
                    break
            self.save()
