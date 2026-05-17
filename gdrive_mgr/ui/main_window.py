# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Main application window: account sidebar + tabbed detail view."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from .. import APP_DISPLAY_NAME, rclone
from ..config import Account, ConfigStore
from ..systemd_units import (
    daemon_active,
    ensure_template_units,
    mount_active,
    start_daemon,
    start_mount,
    stop_mount,
)
from .account_dialog import AddAccountDialog
from .browse_panel import BrowsePanel
from .conflicts_panel import ConflictsPanel
from .disk_panel import DiskUsagePanel
from .status_panel import StatusPanel


class MainWindow(QMainWindow):
    account_state_changed = Signal()

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self.setWindowTitle(APP_DISPLAY_NAME)
        self.resize(1100, 720)
        self.setWindowIcon(QIcon.fromTheme("folder-cloud", QIcon.fromTheme("folder-google-drive")))

        ensure_template_units()
        if not daemon_active():
            try:
                start_daemon()
            except Exception as e:
                print(f"[gdrive-mgr] could not start daemon: {e}")
        self._build_toolbar()
        self._build_body()
        self._refresh_account_list()

        self._status_timer = QTimer(self)
        self._status_timer.setInterval(5000)
        self._status_timer.timeout.connect(self._refresh_current_account)
        self._status_timer.start()

    # ---- chrome ----

    def _build_toolbar(self) -> None:
        tb = QToolBar()
        tb.setMovable(False)
        self.addToolBar(tb)

        add_action = QAction(QIcon.fromTheme("list-add"), "Add account", self)
        add_action.triggered.connect(self._on_add_account)
        tb.addAction(add_action)

        remove_action = QAction(QIcon.fromTheme("list-remove"), "Remove account", self)
        remove_action.triggered.connect(self._on_remove_account)
        tb.addAction(remove_action)

        tb.addSeparator()

        self.mount_toggle = QAction(QIcon.fromTheme("media-playback-start"), "Mount", self)
        self.mount_toggle.triggered.connect(self._on_toggle_mount)
        tb.addAction(self.mount_toggle)

        open_action = QAction(QIcon.fromTheme("folder-open"), "Open in file manager", self)
        open_action.triggered.connect(self._on_open_mount)
        tb.addAction(open_action)

        # Spacer pushes About to the right edge.
        spacer = QWidget()
        spacer.setSizePolicy(self.sizePolicy().Policy.Expanding, self.sizePolicy().Policy.Preferred)
        tb.addWidget(spacer)

        about_action = QAction(QIcon.fromTheme("help-about"), "About", self)
        about_action.triggered.connect(self._on_about)
        tb.addAction(about_action)

    def _on_about(self) -> None:
        from .about_dialog import AboutDialog
        AboutDialog(self).exec()

    def _build_body(self) -> None:
        splitter = QSplitter(Qt.Orientation.Horizontal)

        sidebar = QWidget()
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 8, 8, 8)
        sidebar_layout.addWidget(QLabel("<b>Accounts</b>"))
        self.account_list = QListWidget()
        self.account_list.currentItemChanged.connect(self._on_account_selected)
        sidebar_layout.addWidget(self.account_list, stretch=1)
        splitter.addWidget(sidebar)

        self.detail_stack = QStackedWidget()
        empty = QLabel("No account selected.\n\nClick \"Add account\" in the toolbar.")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setStyleSheet("color: palette(mid);")
        self.detail_stack.addWidget(empty)

        self.tabs = QTabWidget()
        self.status_panel = StatusPanel(self.store)
        self.browse_panel = BrowsePanel(self.store)
        self.conflicts_panel = ConflictsPanel(self.store)
        self.disk_panel = DiskUsagePanel(self.store)
        self.tabs.addTab(self.status_panel, QIcon.fromTheme("dialog-information"), "Status")
        self.tabs.addTab(self.browse_panel, QIcon.fromTheme("folder"), "Browse && Pin")
        self.tabs.addTab(self.conflicts_panel, QIcon.fromTheme("dialog-warning"), "Conflicts")
        self.tabs.addTab(self.disk_panel, QIcon.fromTheme("drive-harddisk"), "Disk Usage")
        # Lazy-load the disk-usage measurement: it can take a few seconds on
        # large VFS caches, so wait until the user actually opens the tab.
        self.tabs.currentChanged.connect(self._on_tab_changed)
        self.detail_stack.addWidget(self.tabs)
        splitter.addWidget(self.detail_stack)

        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([240, 860])

        self.setCentralWidget(splitter)
        self.statusBar().showMessage(f"rclone: {self._safe_rclone_version()}")

    # ---- helpers ----

    @staticmethod
    def _safe_rclone_version() -> str:
        try:
            return rclone.version()
        except rclone.RcloneError as e:
            return f"unavailable ({e})"

    def _refresh_account_list(self) -> None:
        current_name = None
        if self.account_list.currentItem() is not None:
            current_name = self.account_list.currentItem().data(Qt.ItemDataRole.UserRole)

        self.account_list.clear()
        for acc in self.store.config.accounts:
            item = QListWidgetItem(QIcon.fromTheme("folder-cloud"), acc.display_name)
            item.setData(Qt.ItemDataRole.UserRole, acc.remote_name)
            self.account_list.addItem(item)

        if not self.store.config.accounts:
            self.detail_stack.setCurrentIndex(0)
            return

        target_row = 0
        if current_name:
            for i in range(self.account_list.count()):
                if self.account_list.item(i).data(Qt.ItemDataRole.UserRole) == current_name:
                    target_row = i
                    break
        self.account_list.setCurrentRow(target_row)
        self.detail_stack.setCurrentIndex(1)

    def _on_tab_changed(self, index: int) -> None:
        if self.tabs.widget(index) is self.disk_panel:
            self.disk_panel.refresh()

    def _current_account(self) -> Account | None:
        item = self.account_list.currentItem()
        if item is None:
            return None
        return self.store.account(item.data(Qt.ItemDataRole.UserRole))

    def _refresh_current_account(self) -> None:
        acc = self._current_account()
        if acc is None:
            return
        self._update_mount_action(acc)
        self.status_panel.refresh(acc)

    def _update_mount_action(self, acc: Account) -> None:
        active = mount_active(acc.remote_name)
        if active:
            self.mount_toggle.setText("Unmount")
            self.mount_toggle.setIcon(QIcon.fromTheme("media-playback-stop"))
        else:
            self.mount_toggle.setText("Mount")
            self.mount_toggle.setIcon(QIcon.fromTheme("media-playback-start"))

    # ---- actions ----

    def _on_account_selected(self) -> None:
        acc = self._current_account()
        if acc is None:
            return
        self.status_panel.set_account(acc)
        self.browse_panel.set_account(acc)
        self.conflicts_panel.set_account(acc)
        self._update_mount_action(acc)

    def _on_add_account(self) -> None:
        dlg = AddAccountDialog(self.store, self)
        if dlg.exec():
            self._refresh_account_list()
            self.account_state_changed.emit()

    def _on_remove_account(self) -> None:
        acc = self._current_account()
        if acc is None:
            return
        confirm = QMessageBox.question(
            self,
            "Remove account",
            f"Remove account '{acc.display_name}'?\n\n"
            f"This unmounts {acc.mount_path}, removes the rclone remote, "
            f"and deletes app-side state. Local pinned-folder copies are NOT deleted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        try:
            stop_mount(acc.remote_name)
        except Exception:
            pass
        for pin in list(acc.pinned):
            from ..systemd_units import disable_pin
            try:
                disable_pin(acc.remote_name, pin)
            except Exception:
                pass
        try:
            rclone.config_delete(acc.remote_name)
        except Exception:
            pass
        self.store.remove_account(acc.remote_name)
        self._refresh_account_list()
        self.account_state_changed.emit()

    def _on_toggle_mount(self) -> None:
        acc = self._current_account()
        if acc is None:
            return
        try:
            if mount_active(acc.remote_name):
                stop_mount(acc.remote_name)
            else:
                Path(acc.mount_path).mkdir(parents=True, exist_ok=True)
                start_mount(acc)
        except Exception as e:
            QMessageBox.critical(self, "Mount error", str(e))
        self._refresh_current_account()
        self.account_state_changed.emit()

    def _on_open_mount(self) -> None:
        acc = self._current_account()
        if acc is None:
            return
        Path(acc.mount_path).mkdir(parents=True, exist_ok=True)
        import subprocess
        subprocess.Popen(["xdg-open", acc.mount_path])
