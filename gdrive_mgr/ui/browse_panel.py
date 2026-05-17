# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Browse Drive tree and toggle 'Available offline' per folder.

The tree lazy-loads on expand. Each folder row carries a checkbox in column 1:
checking it pins the folder (creates a bisync systemd timer), unchecking
disables the timer (and offers to delete the local copy).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import rclone
from ..config import Account, ConfigStore, PinnedFolder
from ..systemd_units import (
    disable_pin,
    enable_pin,
    pin_last_status,
    run_pin_now,
)


_PLACEHOLDER = "__placeholder__"
_ROLE_PATH = Qt.ItemDataRole.UserRole
_ROLE_ENTRY = Qt.ItemDataRole.UserRole + 1
_ROLE_LOADED = Qt.ItemDataRole.UserRole + 2


class _ListDirWorker(QThread):
    done = Signal(object, list)   # (parent_item_id, entries)
    failed = Signal(object, str)

    def __init__(self, remote: str, path: str, parent_item_id: int) -> None:
        super().__init__()
        self.remote = remote
        self.path = path
        self.parent_item_id = parent_item_id

    def run(self) -> None:
        try:
            entries = rclone.lsjson(self.remote, self.path, dirs_only=True)
        except Exception as e:
            self.failed.emit(self.parent_item_id, str(e))
            return
        self.done.emit(self.parent_item_id, entries)


class BrowsePanel(QWidget):
    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self._account: Account | None = None
        self._workers: list[_ListDirWorker] = []
        self._items_by_id: dict[int, QTreeWidgetItem] = {}

        layout = QVBoxLayout(self)

        header_row = QHBoxLayout()
        self.header_label = QLabel("Select an account.")
        header_row.addWidget(self.header_label, stretch=1)
        self.refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "Refresh")
        self.refresh_btn.clicked.connect(self._reload_root)
        header_row.addWidget(self.refresh_btn)
        layout.addLayout(header_row)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Folder", "Available offline", "Last sync"])
        self.tree.setColumnCount(3)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.itemExpanded.connect(self._on_expand)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.tree, stretch=1)

    # ---- public ----

    def set_account(self, account: Account) -> None:
        self._account = account
        self.header_label.setText(
            f"Browsing <b>{account.display_name}</b>.  "
            f"Check a folder to pin it for offline access."
        )
        self._reload_root()

    # ---- tree management ----

    def _reload_root(self) -> None:
        if self._account is None:
            return
        self.tree.blockSignals(True)
        self.tree.clear()
        self._items_by_id.clear()
        root = QTreeWidgetItem(["My Drive", "", ""])
        root.setIcon(0, QIcon.fromTheme("folder"))
        root.setData(0, _ROLE_PATH, "")
        root.setData(0, _ROLE_LOADED, False)
        root.setFlags(root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        placeholder = QTreeWidgetItem([_PLACEHOLDER])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        root.addChild(placeholder)
        self.tree.addTopLevelItem(root)
        self._items_by_id[id(root)] = root
        self.tree.blockSignals(False)
        self._load_children(root)
        root.setExpanded(True)

    def _load_children(self, parent: QTreeWidgetItem) -> None:
        if self._account is None:
            return
        if parent.data(0, _ROLE_LOADED):
            return
        path = parent.data(0, _ROLE_PATH) or ""
        worker = _ListDirWorker(self._account.remote_name, path, id(parent))
        worker.done.connect(self._on_load_done)
        worker.failed.connect(self._on_load_failed)
        self._workers.append(worker)
        worker.start()

    def _on_load_done(self, parent_item_id: int, entries: list[rclone.DriveEntry]) -> None:
        parent = self._items_by_id.get(parent_item_id)
        if parent is None:
            return
        self.tree.blockSignals(True)
        parent.takeChildren()
        if not entries:
            empty = QTreeWidgetItem(["(no subfolders)", "", ""])
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            parent.addChild(empty)
        else:
            for e in entries:
                self._append_entry(parent, e)
        parent.setData(0, _ROLE_LOADED, True)
        self.tree.blockSignals(False)

    def _on_load_failed(self, parent_item_id: int, msg: str) -> None:
        parent = self._items_by_id.get(parent_item_id)
        if parent is None:
            return
        self.tree.blockSignals(True)
        parent.takeChildren()
        err = QTreeWidgetItem([f"Error: {msg}", "", ""])
        err.setFlags(Qt.ItemFlag.NoItemFlags)
        parent.addChild(err)
        parent.setData(0, _ROLE_LOADED, True)
        self.tree.blockSignals(False)

    def _append_entry(self, parent: QTreeWidgetItem, entry: rclone.DriveEntry) -> None:
        item = QTreeWidgetItem([entry.name, "", ""])
        item.setIcon(0, QIcon.fromTheme("folder"))
        item.setData(0, _ROLE_PATH, entry.path)
        item.setData(0, _ROLE_ENTRY, entry)
        item.setData(0, _ROLE_LOADED, False)
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        is_pinned = self._is_pinned(entry.path)
        item.setCheckState(1, Qt.CheckState.Checked if is_pinned else Qt.CheckState.Unchecked)
        item.setText(2, self._pin_status_text(entry.path))
        placeholder = QTreeWidgetItem([_PLACEHOLDER])
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        item.addChild(placeholder)
        parent.addChild(item)
        self._items_by_id[id(item)] = item

    def _is_pinned(self, remote_path: str) -> bool:
        if self._account is None:
            return False
        return any(p.remote_path == remote_path for p in self._account.pinned)

    def _pin_status_text(self, remote_path: str) -> str:
        if self._account is None:
            return ""
        pin = next((p for p in self._account.pinned if p.remote_path == remote_path), None)
        if pin is None:
            return ""
        if pin.last_sync_ts == 0:
            return "pending first sync"
        import datetime
        ts = datetime.datetime.fromtimestamp(pin.last_sync_ts)
        status = "ok" if pin.last_sync_ok else "failed"
        return f"{ts.strftime('%Y-%m-%d %H:%M')} ({status})"

    # ---- signal handlers ----

    def _on_expand(self, item: QTreeWidgetItem) -> None:
        self._load_children(item)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 1 or self._account is None:
            return
        remote_path = item.data(0, _ROLE_PATH)
        if remote_path is None or remote_path == "":
            return
        checked = item.checkState(1) == Qt.CheckState.Checked
        currently_pinned = self._is_pinned(remote_path)
        if checked and not currently_pinned:
            self._pin_folder(remote_path)
        elif not checked and currently_pinned:
            self._unpin_folder(remote_path)

    def _pin_folder(self, remote_path: str) -> None:
        if self._account is None:
            return
        local_path = str(Path(self.store.config.offline_root) / self._account.remote_name / remote_path)
        Path(local_path).mkdir(parents=True, exist_ok=True)
        pin = PinnedFolder(remote_path=remote_path, local_path=local_path, needs_resync=True)
        self.store.add_pinned(self._account.remote_name, pin)
        try:
            enable_pin(self._account.remote_name, pin)
            run_pin_now(self._account.remote_name, pin)
        except Exception as e:
            QMessageBox.critical(
                self, "Could not enable offline sync",
                f"{e}\n\nThe folder is recorded but its timer is not running.",
            )
        self._refresh_pin_status(remote_path)

    def _unpin_folder(self, remote_path: str) -> None:
        if self._account is None:
            return
        pin = next((p for p in self._account.pinned if p.remote_path == remote_path), None)
        if pin is None:
            return
        try:
            disable_pin(self._account.remote_name, pin)
        except Exception:
            pass

        reply = QMessageBox.question(
            self, "Keep local files?",
            f"Delete the local copy at\n  {pin.local_path}\nas well?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            import shutil
            try:
                shutil.rmtree(pin.local_path)
            except Exception as e:
                QMessageBox.warning(self, "Could not delete", str(e))
        self.store.remove_pinned(self._account.remote_name, remote_path)
        self._refresh_pin_status(remote_path)

    def _refresh_pin_status(self, remote_path: str) -> None:
        for item in self._items_by_id.values():
            if item.data(0, _ROLE_PATH) == remote_path:
                item.setText(2, self._pin_status_text(remote_path))
                break

    # ---- context menu ----

    def _on_context_menu(self, point) -> None:
        item = self.tree.itemAt(point)
        if item is None or self._account is None:
            return
        remote_path = item.data(0, _ROLE_PATH)
        if not remote_path:
            return
        menu = QMenu(self)
        pin = next((p for p in self._account.pinned if p.remote_path == remote_path), None)
        if pin is not None:
            sync_now = QAction(QIcon.fromTheme("view-refresh"), "Sync now", self)
            sync_now.triggered.connect(lambda: self._sync_now(pin))
            menu.addAction(sync_now)
            open_local = QAction(QIcon.fromTheme("folder-open"), "Open local copy", self)
            open_local.triggered.connect(lambda: self._open_path(pin.local_path))
            menu.addAction(open_local)
            menu.addSeparator()
            show_status = QAction("Show systemd status", self)
            show_status.triggered.connect(
                lambda: QMessageBox.information(
                    self, "Sync status", pin_last_status(self._account.remote_name, pin) or "(no info)"
                )
            )
            menu.addAction(show_status)
        if not menu.isEmpty():
            menu.exec(self.tree.viewport().mapToGlobal(point))

    def _sync_now(self, pin: PinnedFolder) -> None:
        if self._account is None:
            return
        try:
            run_pin_now(self._account.remote_name, pin)
        except Exception as e:
            QMessageBox.warning(self, "Could not start sync", str(e))

    def _open_path(self, path: str) -> None:
        import subprocess
        Path(path).mkdir(parents=True, exist_ok=True)
        subprocess.Popen(["xdg-open", path])
