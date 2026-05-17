# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Add-account wizard: drives the rclone OAuth flow and persists the account."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from .. import rclone
from ..config import Account, ConfigStore


_SAFE_NAME = re.compile(r"^[a-zA-Z0-9_-]+$")


class _AuthorizeWorker(QThread):
    """Drive the rclone OAuth + config-create flow in a background thread.

    Emits url_ready once the OAuth URL is detected, info for every other log
    line, finished_ok when the remote was successfully created, and failed
    with the tail of rclone's output if it exited non-zero.
    """

    url_ready = Signal(str)
    finished_ok = Signal()
    info = Signal(str)
    failed = Signal(str)

    def __init__(self, remote_name: str) -> None:
        super().__init__()
        self._remote_name = remote_name

    def run(self) -> None:
        try:
            for kind, payload in rclone.create_drive_remote(self._remote_name):
                if kind == "url":
                    self.url_ready.emit(payload)
                elif kind == "success":
                    self.finished_ok.emit()
                    return
                elif kind == "error":
                    self.failed.emit(payload or "rclone config create failed.")
                    return
                else:
                    self.info.emit(payload)
            self.failed.emit("rclone exited without confirming success.")
        except Exception as e:
            self.failed.emit(str(e))


class _IntroPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Add a Google Drive account")
        self.setSubTitle(
            "Pick a short identifier and a friendly display name. "
            "The identifier becomes the rclone remote name and must be unique."
        )

        layout = QFormLayout(self)
        self.remote_name = QLineEdit()
        self.remote_name.setPlaceholderText("e.g. gdrive-personal")
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("e.g. Personal Drive")
        layout.addRow("Identifier:", self.remote_name)
        layout.addRow("Display name:", self.display_name)

        self.registerField("remote_name*", self.remote_name)
        self.registerField("display_name*", self.display_name)

    def isComplete(self) -> bool:
        name = self.remote_name.text().strip()
        return bool(_SAFE_NAME.match(name)) and bool(self.display_name.text().strip())

    def validatePage(self) -> bool:
        name = self.remote_name.text().strip()
        try:
            if name in rclone.list_remotes():
                QMessageBox.critical(
                    self,
                    "Remote already exists",
                    f"An rclone remote named {name!r} already exists. "
                    "Pick a different identifier or remove the existing one first "
                    "with: rclone config delete " + name,
                )
                return False
        except rclone.RcloneError:
            pass  # if rclone is unreachable, the next page will surface a clearer error
        return True


class _AuthPage(QWizardPage):
    """Drives `rclone config create` (OAuth + remote write in one step) in a
    worker thread. The page completes when rclone exits 0, meaning the remote
    has already been written to the rclone config."""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Authorize with Google")
        self.setSubTitle(
            "A browser window will open for sign-in. If it doesn't, click the URL below."
        )
        self._ok = False
        self._worker: _AuthorizeWorker | None = None

        layout = QVBoxLayout(self)

        self.url_label = QLabel("Starting rclone…")
        self.url_label.setWordWrap(True)
        self.url_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.url_label.setOpenExternalLinks(True)
        layout.addWidget(self.url_label)

        self.open_button = QPushButton("Open in browser")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_url)
        layout.addWidget(self.open_button)

        layout.addWidget(QLabel("Output:"))
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        f = QFont("monospace")
        f.setStyleHint(QFont.StyleHint.Monospace)
        self.log.setFont(f)
        layout.addWidget(self.log, stretch=1)

        self._url: str | None = None

    def initializePage(self) -> None:
        self._ok = False
        self.log.clear()
        self.url_label.setText("Starting rclone…")
        self.open_button.setEnabled(False)
        self.completeChanged.emit()

        remote_name = self.wizard().field("remote_name").strip()
        self._worker = _AuthorizeWorker(remote_name)
        self._worker.url_ready.connect(self._on_url)
        self._worker.finished_ok.connect(self._on_ok)
        self._worker.info.connect(lambda s: self.log.appendPlainText(s))
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def isComplete(self) -> bool:
        return self._ok

    def _on_url(self, url: str) -> None:
        self._url = url
        self.url_label.setText(
            f'<a href="{url}">{url}</a><br><br>'
            "When prompted by Google, click <b>Advanced → Go to rclone (unsafe)</b> "
            "and grant <b>all</b> requested permissions."
        )
        self.open_button.setEnabled(True)
        QDesktopServices.openUrl(QUrl(url))

    def _on_ok(self) -> None:
        self._ok = True
        self.log.appendPlainText("\n✓ Remote created.")
        self.completeChanged.emit()

    def _on_failed(self, msg: str) -> None:
        self.log.appendPlainText(f"\n✗ Failed: {msg}")
        QMessageBox.critical(self, "Authorization failed", msg)

    def _open_url(self) -> None:
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))


class _FinishPage(QWizardPage):
    def __init__(self) -> None:
        super().__init__()
        self.setTitle("Account ready")
        self.setSubTitle(
            "The Google Drive remote will be saved and mounted on demand."
        )
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

    def initializePage(self) -> None:
        wizard = self.wizard()
        assert isinstance(wizard, AddAccountDialog)
        name = wizard.field("remote_name")
        display = wizard.field("display_name")
        self.summary.setText(
            f"<b>Identifier:</b> {name}<br>"
            f"<b>Display name:</b> {display}<br>"
            f"<b>Mount point:</b> {wizard.proposed_mount_path()}<br><br>"
            "Click Finish to save."
        )


class AddAccountDialog(QWizard):
    def __init__(self, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.store = store
        self.setWindowTitle("Add Google Drive account")
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setMinimumSize(640, 480)

        self.intro_page = _IntroPage()
        self.auth_page = _AuthPage()
        self.finish_page = _FinishPage()
        self.addPage(self.intro_page)
        self.addPage(self.auth_page)
        self.addPage(self.finish_page)

    def proposed_mount_path(self) -> str:
        name = self.field("remote_name") or "gdrive"
        return str(Path.home() / "GoogleDrive" / name)

    def accept(self) -> None:
        remote_name = self.field("remote_name").strip()
        display_name = self.field("display_name").strip()

        # rclone config create already wrote the remote; just sanity-check it
        # exists and persist the app-side Account record.
        if remote_name not in rclone.list_remotes():
            QMessageBox.critical(
                self,
                "Remote missing",
                f"rclone reports no remote named {remote_name!r}. "
                "Authorization did not complete.",
            )
            return

        account = Account(
            remote_name=remote_name,
            display_name=display_name,
            mount_path=self.proposed_mount_path(),
        )
        try:
            self.store.add_account(account)
        except ValueError as e:
            QMessageBox.critical(self, "Account exists", str(e))
            return
        super().accept()
