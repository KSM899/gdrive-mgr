# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""About dialog with version, attribution, and license info."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)

from .. import APP_DISPLAY_NAME, APP_VERSION


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About " + APP_DISPLAY_NAME)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)

        # Header row: icon + name/version
        header = QHBoxLayout()
        icon_label = QLabel()
        icon = QIcon.fromTheme("folder-cloud")
        if not icon.isNull():
            icon_label.setPixmap(icon.pixmap(64, 64))
        header.addWidget(icon_label)

        title = QLabel(
            f"<h2 style='margin-bottom: 0'>{APP_DISPLAY_NAME}</h2>"
            f"<p style='margin-top: 4px; color: palette(mid)'>Version {APP_VERSION}</p>"
        )
        title.setTextFormat(Qt.TextFormat.RichText)
        header.addWidget(title, stretch=1)
        layout.addLayout(header)

        # Description
        desc = QLabel(
            "<p>A KDE-native Google Drive manager built on <b>rclone</b>. "
            "Files-on-demand mount with per-folder and per-file pinning, "
            "background sync, in-app sharing, and Dolphin overlay badges.</p>"
            "<p style='color: palette(mid)'>"
            "Built fully using AI by <b>Khalid Said</b>."
            "</p>"
        )
        desc.setWordWrap(True)
        desc.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(desc)

        # License + links
        meta = QLabel(
            "<p><b>License:</b> GNU General Public License v3.0 or later</p>"
            "<p><b>Source:</b> "
            "<a href='https://github.com/KSM899/gdrive-mgr'>"
            "github.com/KSM899/gdrive-mgr</a></p>"
            "<p style='color: palette(mid); font-size: 9pt'>"
            "This program is free software: you can redistribute it and/or modify "
            "it under the terms of the GNU GPL as published by the Free Software "
            "Foundation, either version 3 of the License, or (at your option) any "
            "later version. This program is distributed in the hope that it will "
            "be useful, but WITHOUT ANY WARRANTY; without even the implied warranty "
            "of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE."
            "</p>"
        )
        meta.setOpenExternalLinks(True)
        meta.setWordWrap(True)
        meta.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(meta)

        # Dependencies note
        deps = QLabel(
            "<p style='color: palette(mid); font-size: 9pt'>"
            "Powered by <a href='https://rclone.org'>rclone</a>, "
            "<a href='https://www.qt.io'>Qt 6</a> / PySide6, and "
            "<a href='https://kde.org/frameworks'>KDE Frameworks 6</a>."
            "</p>"
        )
        deps.setOpenExternalLinks(True)
        deps.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(deps)

        # Close button
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
