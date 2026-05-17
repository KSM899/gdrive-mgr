# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Disk usage breakdown — what gdrive-mgr is actually using locally.

The Properties dialog in Dolphin always shows a file's true (cloud) size for
items in the FUSE mount, which is misleading because those files may not be
on disk yet. This panel measures actual local footprint:

  - VFS cache for each account (~/.cache/rclone/vfs/<remote>/)
  - Pinned folders' on-disk size (~/GoogleDrive-Offline/<remote>/<path>/)
  - Pinned files' on-disk size

A worker thread does the os.walk so the UI never freezes on big trees.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import Account, ConfigStore


def _fmt_bytes(n: int) -> str:
    if n < 0:
        return "—"
    if n == 0:
        return "0 B"
    f = float(n)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if f < 1024:
            return f"{f:.1f} {unit}" if unit != "B" else f"{int(f)} B"
        f /= 1024
    return f"{f:.1f} PiB"


def _dir_size(path: Path) -> int:
    """Sum of allocated blocks (actual disk usage), recursive. 0 if missing.

    We use st_blocks * 512 instead of st_size because that's the real
    on-disk footprint — sparse files and partially-cached rclone VFS files
    can have st_size > actual allocation.
    """
    if not path.exists():
        return 0
    total = 0
    for root, dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            total += st.st_blocks * 512
    return total


def _file_size(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        st = path.stat()
    except OSError:
        return 0
    return st.st_blocks * 512


@dataclass
class _AccountUsage:
    remote_name: str
    display_name: str
    vfs_cache_bytes: int
    pinned_folders_bytes: int
    pinned_files_bytes: int
    pinned_folder_breakdown: list[tuple[str, int]]
    pinned_file_breakdown: list[tuple[str, int]]

    @property
    def total_bytes(self) -> int:
        return self.vfs_cache_bytes + self.pinned_folders_bytes + self.pinned_files_bytes


class _UsageWorker(QThread):
    done = Signal(object)  # list[_AccountUsage]

    def __init__(self, accounts: list[Account]) -> None:
        super().__init__()
        self._accounts = list(accounts)

    def run(self) -> None:
        results: list[_AccountUsage] = []
        cache_root = Path.home() / ".cache" / "rclone" / "vfs"
        for acc in self._accounts:
            vfs = cache_root / acc.remote_name
            vfs_size = _dir_size(vfs)

            folder_breakdown: list[tuple[str, int]] = []
            folders_total = 0
            for p in acc.pinned:
                size = _dir_size(Path(p.local_path))
                folder_breakdown.append((p.remote_path, size))
                folders_total += size

            file_breakdown: list[tuple[str, int]] = []
            files_total = 0
            for fp in acc.pinned_files:
                size = _file_size(Path(fp.local_path))
                file_breakdown.append((fp.remote_path, size))
                files_total += size

            results.append(_AccountUsage(
                remote_name=acc.remote_name,
                display_name=acc.display_name,
                vfs_cache_bytes=vfs_size,
                pinned_folders_bytes=folders_total,
                pinned_files_bytes=files_total,
                pinned_folder_breakdown=folder_breakdown,
                pinned_file_breakdown=file_breakdown,
            ))
        self.done.emit(results)


class DiskUsagePanel(QWidget):
    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self._worker: _UsageWorker | None = None

        layout = QVBoxLayout(self)

        header = QHBoxLayout()
        self.summary = QLabel("Click Refresh to measure local disk usage.")
        self.summary.setWordWrap(True)
        header.addWidget(self.summary, stretch=1)
        self.refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Item", "Size on disk"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.tree, stretch=1)

        hint = QLabel(
            "<i>Sizes are <b>allocated disk blocks</b> — what files actually use "
            "on this disk, not the apparent (cloud) size shown in Dolphin's Properties dialog. "
            "VFS cache is what rclone has streamed and kept around for recent reads; "
            "pinned items are the bisync / file-copy local mirrors.</i>"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid); padding: 6px;")
        layout.addWidget(hint)

    def refresh(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.summary.setText("Measuring…")
        self.refresh_btn.setEnabled(False)
        self._worker = _UsageWorker(self.store.config.accounts)
        self._worker.done.connect(self._on_done)
        self._worker.finished.connect(lambda: self.refresh_btn.setEnabled(True))
        self._worker.start()

    def _on_done(self, results: list[_AccountUsage]) -> None:
        self.tree.clear()
        if not results:
            self.summary.setText("No accounts configured.")
            return

        grand_total = 0
        for acc in results:
            grand_total += acc.total_bytes
            acc_item = QTreeWidgetItem([
                acc.display_name,
                _fmt_bytes(acc.total_bytes),
            ])
            acc_item.setIcon(0, QIcon.fromTheme("folder-cloud"))
            self.tree.addTopLevelItem(acc_item)

            cache = QTreeWidgetItem([
                "On-demand cache (rclone VFS)",
                _fmt_bytes(acc.vfs_cache_bytes),
            ])
            cache.setIcon(0, QIcon.fromTheme("drive-harddisk"))
            acc_item.addChild(cache)

            pin_folders = QTreeWidgetItem([
                f"Pinned folders ({len(acc.pinned_folder_breakdown)})",
                _fmt_bytes(acc.pinned_folders_bytes),
            ])
            pin_folders.setIcon(0, QIcon.fromTheme("folder-favorites"))
            acc_item.addChild(pin_folders)
            for path, size in sorted(acc.pinned_folder_breakdown, key=lambda x: -x[1]):
                child = QTreeWidgetItem([path, _fmt_bytes(size)])
                pin_folders.addChild(child)

            pin_files = QTreeWidgetItem([
                f"Pinned files ({len(acc.pinned_file_breakdown)})",
                _fmt_bytes(acc.pinned_files_bytes),
            ])
            pin_files.setIcon(0, QIcon.fromTheme("text-x-generic"))
            acc_item.addChild(pin_files)
            for path, size in sorted(acc.pinned_file_breakdown, key=lambda x: -x[1]):
                child = QTreeWidgetItem([path, _fmt_bytes(size)])
                pin_files.addChild(child)

            acc_item.setExpanded(True)

        self.summary.setText(
            f"<b>Total local footprint: {_fmt_bytes(grand_total)}</b> "
            f"across {len(results)} account(s)."
        )
