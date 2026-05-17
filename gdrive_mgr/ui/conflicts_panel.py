# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Show bisync conflict files across all pinned folders for the current account.

bisync writes conflict losers as `<name>.conflict<n>`. The panel lists them and
lets the user keep-local (delete the conflict copy), keep-conflict (replace
the original with it), or open both side-by-side in a diff viewer.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import rclone
from ..config import Account, ConfigStore


class ConflictsPanel(QWidget):
    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self._account: Account | None = None

        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.label = QLabel("Select an account.")
        header.addWidget(self.label, stretch=1)
        self.refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "Refresh")
        self.refresh_btn.clicked.connect(self.refresh)
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self.list = QListWidget()
        self.list.setAlternatingRowColors(True)
        layout.addWidget(self.list, stretch=1)

        actions = QHBoxLayout()
        self.keep_local_btn = QPushButton(QIcon.fromTheme("edit-delete"), "Keep local (delete conflict)")
        self.keep_local_btn.clicked.connect(self._keep_local)
        self.keep_conflict_btn = QPushButton(QIcon.fromTheme("document-save"), "Replace with conflict")
        self.keep_conflict_btn.clicked.connect(self._keep_conflict)
        self.diff_btn = QPushButton(QIcon.fromTheme("text-x-changelog"), "Open diff")
        self.diff_btn.clicked.connect(self._open_diff)
        for b in (self.keep_local_btn, self.keep_conflict_btn, self.diff_btn):
            b.setEnabled(False)
            actions.addWidget(b)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.list.itemSelectionChanged.connect(self._update_buttons)

    def set_account(self, account: Account) -> None:
        self._account = account
        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        if self._account is None:
            self.label.setText("Select an account.")
            self._update_buttons()
            return
        total = 0
        for pin in self._account.pinned:
            for path in rclone.find_conflicts(pin.local_path):
                item = QListWidgetItem(QIcon.fromTheme("dialog-warning"), self._display_for(pin.local_path, path))
                item.setData(Qt.ItemDataRole.UserRole, (pin.local_path, path))
                self.list.addItem(item)
                total += 1
        if total == 0:
            self.label.setText(f"<b>{self._account.display_name}</b>: no conflicts. 🎉")
        else:
            self.label.setText(f"<b>{self._account.display_name}</b>: {total} conflict file(s).")
        self._update_buttons()

    @staticmethod
    def _display_for(local_root: str, full_path: str) -> str:
        try:
            return str(Path(full_path).relative_to(local_root))
        except ValueError:
            return full_path

    def _selected(self) -> tuple[str, str] | None:
        item = self.list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _update_buttons(self) -> None:
        enabled = self._selected() is not None
        for b in (self.keep_local_btn, self.keep_conflict_btn, self.diff_btn):
            b.setEnabled(enabled)

    def _original_for(self, conflict_path: str) -> str:
        """`foo.txt.conflict1` -> `foo.txt`. Trim `.conflict<digits>` suffix."""
        p = Path(conflict_path)
        name = p.name
        if ".conflict" in name:
            base, _, _ = name.rpartition(".conflict")
            return str(p.with_name(base))
        return str(p.with_suffix(""))

    def _keep_local(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        _, conflict_path = sel
        try:
            Path(conflict_path).unlink()
        except Exception as e:
            QMessageBox.warning(self, "Could not delete", str(e))
            return
        self.refresh()

    def _keep_conflict(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        _, conflict_path = sel
        original = self._original_for(conflict_path)
        try:
            shutil.move(conflict_path, original)
        except Exception as e:
            QMessageBox.warning(self, "Could not replace", str(e))
            return
        self.refresh()

    def _open_diff(self) -> None:
        sel = self._selected()
        if sel is None:
            return
        _, conflict_path = sel
        original = self._original_for(conflict_path)
        import subprocess
        for tool in ("kompare", "meld", "diffuse"):
            if shutil.which(tool):
                subprocess.Popen([tool, original, conflict_path])
                return
        QMessageBox.information(
            self, "No diff tool",
            "Install kompare, meld, or diffuse to compare conflicts.",
        )
