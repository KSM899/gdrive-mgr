# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Per-path sync status, persisted to a JSON snapshot and broadcast on change.

The daemon owns this file; the tray, app, and Dolphin overlay plugin all read
from it. We write the whole file on every change — small enough (at most a few
thousand entries) that atomic rewrites are cheaper than a real DB or socket
protocol, and dead-simple for the C++ plugin to consume.

Path matching for queries: we look up by exact absolute path first, then walk
up the directory tree. So if ~/GoogleDrive-Offline/x/Work is 'syncing',
~/GoogleDrive-Offline/x/Work/sub/file.txt inherits that status.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from threading import RLock

STATE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "gdrive-mgr"
STATUS_PATH = STATE_DIR / "status.json"


class SyncState(str, Enum):
    SYNCED = "synced"
    SYNCING = "syncing"
    ERROR = "error"
    PENDING = "pending"        # queued for sync, not yet running
    ONLINE_ONLY = "online_only"  # exists in mount, not pinned


@dataclass
class PathStatus:
    path: str               # absolute local path (the pinned-folder root or mount path)
    state: str              # one of SyncState values
    ts: float = 0.0         # last update timestamp
    message: str = ""       # human-readable detail (e.g. error tail)

    def to_dict(self) -> dict:
        return asdict(self)


class StatusStore:
    """Thread-safe owner of status.json. Daemon writes; everyone else reads."""

    def __init__(self, path: Path = STATUS_PATH) -> None:
        self.path = path
        self._lock = RLock()
        self._entries: dict[str, PathStatus] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return
        for raw in data.get("entries", []):
            try:
                ps = PathStatus(**raw)
                self._entries[ps.path] = ps
            except TypeError:
                continue

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "ts": time.time(),
            "entries": [e.to_dict() for e in self._entries.values()],
        }
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2))
        # Owner-readable only — paths in here can reveal directory structure
        # of pinned content. Also: the Dolphin overlay plugin reads this as
        # the same user, so 0600 is sufficient.
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def set(self, path: str, state: SyncState, message: str = "") -> None:
        with self._lock:
            self._entries[path] = PathStatus(
                path=path, state=state.value, ts=time.time(), message=message
            )
            self._save()

    def remove(self, path: str) -> None:
        with self._lock:
            self._entries.pop(path, None)
            self._save()

    def all(self) -> list[PathStatus]:
        with self._lock:
            return list(self._entries.values())

    def lookup(self, abs_path: str) -> PathStatus | None:
        """Return status for abs_path or its nearest registered ancestor.
        Useful for the overlay plugin: a file under a pinned folder shows the
        folder's status."""
        with self._lock:
            p = Path(abs_path).resolve()
            if str(p) in self._entries:
                return self._entries[str(p)]
            for ancestor in p.parents:
                key = str(ancestor)
                if key in self._entries:
                    return self._entries[key]
        return None

    def global_state(self) -> SyncState:
        """Aggregate over all entries — what the tray icon should show."""
        with self._lock:
            states = {e.state for e in self._entries.values()}
        if SyncState.ERROR.value in states:
            return SyncState.ERROR
        if SyncState.SYNCING.value in states or SyncState.PENDING.value in states:
            return SyncState.SYNCING
        return SyncState.SYNCED
