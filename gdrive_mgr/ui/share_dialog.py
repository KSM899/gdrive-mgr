# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Native Qt dialog for sharing a Drive file/folder with specific people.

Pure local UI — talks to Google Drive's REST API directly (via gdrive_mgr.drive_api)
using rclone's OAuth token. No browser hop required.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import drive_api


# (label shown in UI, Drive API role string)
_ROLES: list[tuple[str, str]] = [
    ("Viewer", "reader"),
    ("Commenter", "commenter"),
    ("Editor", "writer"),
]


class _LoadPermsWorker(QThread):
    done = Signal(list)
    failed = Signal(str)

    def __init__(self, remote: str, file_id: str) -> None:
        super().__init__()
        self._remote = remote
        self._file_id = file_id

    def run(self) -> None:
        try:
            self.done.emit(drive_api.list_permissions(self._remote, self._file_id))
        except Exception as e:
            self.failed.emit(str(e))


class _AddPermWorker(QThread):
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, remote: str, file_id: str, email: str, role: str, notify: bool, message: str) -> None:
        super().__init__()
        self._remote = remote
        self._file_id = file_id
        self._email = email
        self._role = role
        self._notify = notify
        self._message = message

    def run(self) -> None:
        try:
            result = drive_api.add_permission(
                self._remote, self._file_id, self._email, self._role,
                notify=self._notify, message=self._message,
            )
            self.done.emit(result or {})
        except Exception as e:
            self.failed.emit(str(e))


class _RemovePermWorker(QThread):
    done = Signal()
    failed = Signal(str)

    def __init__(self, remote: str, file_id: str, perm_id: str) -> None:
        super().__init__()
        self._remote = remote
        self._file_id = file_id
        self._perm_id = perm_id

    def run(self) -> None:
        try:
            drive_api.remove_permission(self._remote, self._file_id, self._perm_id)
            self.done.emit()
        except Exception as e:
            self.failed.emit(str(e))


class ShareDialog(QDialog):
    """Pop-up for managing 'share with specific people' on a Drive item."""

    def __init__(
        self,
        remote: str,
        file_id: str,
        display_path: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._remote = remote
        self._file_id = file_id
        self._display_path = display_path
        self._workers: list[QThread] = []

        self.setWindowTitle("Share — " + display_path)
        self.resize(620, 520)
        self.setWindowIcon(QIcon.fromTheme("document-share"))

        layout = QVBoxLayout(self)

        title = QLabel(f"<h3>Share <i>{display_path}</i></h3>"
                       f"<span style='color: palette(mid)'>{remote}</span>")
        title.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(title)

        # ---- Add-person row ----
        add_row = QHBoxLayout()
        self.email_input = QLineEdit()
        self.email_input.setPlaceholderText("name@example.com")
        self.email_input.returnPressed.connect(self._on_share)
        self.role_combo = QComboBox()
        for label, _ in _ROLES:
            self.role_combo.addItem(label)
        self.role_combo.setCurrentIndex(0)
        add_row.addWidget(self.email_input, stretch=2)
        add_row.addWidget(self.role_combo)
        layout.addLayout(add_row)

        self.notify_check = QCheckBox("Notify by email")
        self.notify_check.setChecked(True)
        layout.addWidget(self.notify_check)

        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Optional message (sent with the email)")
        layout.addWidget(self.message_input)

        self.share_btn = QPushButton(QIcon.fromTheme("document-share"), "Share")
        self.share_btn.setDefault(True)
        self.share_btn.clicked.connect(self._on_share)
        layout.addWidget(self.share_btn)

        # ---- People list ----
        layout.addWidget(QLabel("<b>People with access:</b>"))
        self.perms_list = QListWidget()
        self.perms_list.setAlternatingRowColors(True)
        self.perms_list.itemSelectionChanged.connect(self._update_remove_btn)
        layout.addWidget(self.perms_list, stretch=1)

        # ---- Bottom actions ----
        bottom = QHBoxLayout()
        self.remove_btn = QPushButton(QIcon.fromTheme("list-remove"), "Remove access")
        self.remove_btn.setEnabled(False)
        self.remove_btn.clicked.connect(self._on_remove)
        self.refresh_btn = QPushButton(QIcon.fromTheme("view-refresh"), "Refresh")
        self.refresh_btn.clicked.connect(self._refresh)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        bottom.addWidget(self.remove_btn)
        bottom.addStretch(1)
        bottom.addWidget(self.refresh_btn)
        bottom.addWidget(close_btn)
        layout.addLayout(bottom)

        self._refresh()

    # ---- list loading ----

    def _refresh(self) -> None:
        self.perms_list.clear()
        placeholder = QListWidgetItem("Loading…")
        placeholder.setFlags(Qt.ItemFlag.NoItemFlags)
        self.perms_list.addItem(placeholder)
        worker = _LoadPermsWorker(self._remote, self._file_id)
        worker.done.connect(self._on_perms_loaded)
        worker.failed.connect(self._on_load_failed)
        self._workers.append(worker)
        worker.start()

    def _on_perms_loaded(self, perms: list) -> None:
        self.perms_list.clear()
        if not perms:
            empty = QListWidgetItem("(no shares)")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)
            self.perms_list.addItem(empty)
            return
        for p in perms:
            label = self._format_perm(p)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p)
            # Owner can't be removed — Drive forbids it via the API.
            if p.get("role") == "owner":
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)
                f = item.font()
                f.setItalic(True)
                item.setFont(f)
            self.perms_list.addItem(item)

    @staticmethod
    def _format_perm(p: dict) -> str:
        role = p.get("role", "?")
        ptype = p.get("type", "?")
        if ptype == "anyone":
            who = "Anyone with the link"
        elif ptype == "user":
            who = p.get("emailAddress") or p.get("displayName") or "(unknown user)"
        elif ptype == "group":
            who = (p.get("emailAddress") or p.get("displayName") or "(unknown group)") + " (group)"
        elif ptype == "domain":
            who = (p.get("domain") or "(unknown domain)") + " (domain)"
        else:
            who = "(unknown)"
        role_label = {"reader": "Viewer", "commenter": "Commenter", "writer": "Editor", "owner": "Owner"}.get(role, role)
        return f"{who}    —    {role_label}"

    def _on_load_failed(self, msg: str) -> None:
        self.perms_list.clear()
        err = QListWidgetItem(f"Failed to load: {msg}")
        err.setFlags(Qt.ItemFlag.NoItemFlags)
        self.perms_list.addItem(err)

    # ---- add ----

    def _on_share(self) -> None:
        email = self.email_input.text().strip()
        if "@" not in email or "." not in email.split("@", 1)[1]:
            QMessageBox.warning(self, "Invalid email", "Enter a valid email address.")
            return
        role = _ROLES[self.role_combo.currentIndex()][1]
        notify = self.notify_check.isChecked()
        message = self.message_input.text().strip()

        self.share_btn.setEnabled(False)
        worker = _AddPermWorker(self._remote, self._file_id, email, role, notify, message)
        worker.done.connect(self._on_share_done)
        worker.failed.connect(self._on_share_failed)
        self._workers.append(worker)
        worker.start()

    def _on_share_done(self, _result: dict) -> None:
        self.share_btn.setEnabled(True)
        self.email_input.clear()
        self.message_input.clear()
        self._refresh()

    def _on_share_failed(self, msg: str) -> None:
        self.share_btn.setEnabled(True)
        QMessageBox.critical(self, "Could not share", msg)

    # ---- remove ----

    def _selected_perm(self) -> dict | None:
        item = self.perms_list.currentItem()
        if item is None:
            return None
        return item.data(Qt.ItemDataRole.UserRole)

    def _update_remove_btn(self) -> None:
        p = self._selected_perm()
        self.remove_btn.setEnabled(p is not None and p.get("role") != "owner")

    def _on_remove(self) -> None:
        p = self._selected_perm()
        if not p:
            return
        confirm = QMessageBox.question(
            self,
            "Remove access",
            f"Remove access for:\n\n{self._format_perm(p)}?",
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        self.remove_btn.setEnabled(False)
        worker = _RemovePermWorker(self._remote, self._file_id, p["id"])
        worker.done.connect(self._refresh)
        worker.failed.connect(lambda e: QMessageBox.warning(self, "Could not remove", e))
        self._workers.append(worker)
        worker.start()
