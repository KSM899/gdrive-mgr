# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Entry point: `python -m gdrive_mgr` launches the GUI."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QMessageBox,
    QStyleFactory,
    QSystemTrayIcon,
)

from . import APP_DISPLAY_NAME, APP_ID, APP_VERSION, rclone
from .config import ConfigStore
from .ui.main_window import MainWindow
from .ui.tray import TrayIcon


STYLESHEET_PATH = Path(__file__).resolve().parent.parent / "resources" / "styles" / "modern.qss"


def _select_best_style(app: QApplication) -> str:
    """Pick the best built-in Qt style. We deliberately do NOT try to load the
    system Breeze plugin because it's built against a different Qt minor
    version than the one bundled in our PySide6 venv (ABI-incompatible —
    causes a crash). Use Fusion as the consistent base; the visual polish
    comes from our shipped stylesheet, not from Breeze."""
    for name in ("Fusion", "Windows"):
        if name in QStyleFactory.keys():
            app.setStyle(QStyleFactory.create(name))
            return name
    return app.style().objectName()


def _apply_stylesheet(app: QApplication) -> None:
    """Load the modern QSS and apply it app-wide.
    Override with GDRIVE_MGR_QSS=/path/to/file to experiment."""
    qss_path = Path(os.environ.get("GDRIVE_MGR_QSS", "") or STYLESHEET_PATH)
    if not qss_path.exists():
        return
    try:
        app.setStyleSheet(qss_path.read_text())
    except OSError as e:
        print(f"[gdrive-mgr] could not load stylesheet {qss_path}: {e}", file=sys.stderr)


def main() -> int:
    # Make sure Qt finds the system KDE icon theme even from a venv install.
    QIcon.setFallbackThemeName("breeze")

    app = QApplication(sys.argv)
    app.setApplicationName(APP_DISPLAY_NAME)
    app.setApplicationDisplayName(APP_DISPLAY_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(False)  # tray keeps us alive
    app.setWindowIcon(QIcon.fromTheme("folder-cloud"))

    active_style = _select_best_style(app)
    _apply_stylesheet(app)
    if os.environ.get("GDRIVE_MGR_DEBUG"):
        print(f"[gdrive-mgr] active Qt style: {active_style}", file=sys.stderr)

    signal.signal(signal.SIGINT, signal.SIG_DFL)
    sigint_timer = QTimer()
    sigint_timer.start(200)
    sigint_timer.timeout.connect(lambda: None)

    try:
        rclone.rclone_path()
    except rclone.RcloneError as e:
        QMessageBox.critical(None, "rclone missing", str(e))
        return 2

    store = ConfigStore()
    window = MainWindow(store)
    window.show()

    tray: TrayIcon | None = None
    if QSystemTrayIcon.isSystemTrayAvailable():
        tray = TrayIcon(store, window)
        tray.show()

    rc = app.exec()
    # Keep `tray` referenced until shutdown
    del tray
    return rc


if __name__ == "__main__":
    sys.exit(main())
