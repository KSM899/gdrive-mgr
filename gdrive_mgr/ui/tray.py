# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""System-tray icon: shows global sync state at a glance + quick toggles.

Icon color reflects the daemon's StatusStore aggregate:
  green check    — all pinned folders synced (or no pinned folders)
  yellow refresh — at least one folder is syncing or pending
  red error      — at least one folder has a sync error

We render the badge ourselves on top of a base folder-cloud icon so it works
in any KDE icon theme without needing custom assets shipped with the app.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, QTimer, Qt
from PySide6.QtGui import QAction, QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from ..config import ConfigStore
from ..status import StatusStore, SyncState
from ..systemd_units import (
    daemon_active,
    mount_active,
    run_pin_now,
    start_daemon,
    start_mount,
    stop_mount,
)


def _badge_color(state: SyncState) -> QColor:
    if state == SyncState.ERROR:
        return QColor("#d32f2f")    # red
    if state == SyncState.SYNCING or state == SyncState.PENDING:
        return QColor("#f9a825")    # amber
    return QColor("#43a047")        # green


def _compose_badge_icon(base_name: str, state: SyncState) -> QIcon:
    """Take a themed base icon and paint a small colored dot in the bottom-right
    corner. Returns a QIcon usable at any size."""
    base = QIcon.fromTheme(base_name)
    if base.isNull():
        base = QIcon.fromTheme("folder-cloud")
    if base.isNull():
        # Fallback: an empty pixmap we paint the badge onto solo
        pix = QPixmap(64, 64)
        pix.fill(Qt.GlobalColor.transparent)
    else:
        pix = base.pixmap(64, 64)

    painter = QPainter(pix)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = _badge_color(state)
    radius = 22
    rect = QRect(pix.width() - radius - 2, pix.height() - radius - 2, radius, radius)
    painter.setPen(QPen(QColor("white"), 3))
    painter.setBrush(QBrush(color))
    painter.drawEllipse(rect)
    painter.end()
    return QIcon(pix)


class TrayIcon(QSystemTrayIcon):
    def __init__(self, store: ConfigStore, main_window) -> None:
        super().__init__()
        self.store = store
        self.status_store = StatusStore()
        self.main_window = main_window
        self._last_state: SyncState | None = None

        self.setIcon(_compose_badge_icon("folder-cloud", SyncState.SYNCED))
        self.setToolTip("Google Drive Manager")
        self._menu = QMenu()
        self.setContextMenu(self._menu)
        self.activated.connect(self._on_activated)
        self._rebuild_menu()
        self._refresh_badge()

        self._menu_timer = QTimer(self)
        self._menu_timer.setInterval(10_000)
        self._menu_timer.timeout.connect(self._rebuild_menu)
        self._menu_timer.start()

        self._badge_timer = QTimer(self)
        self._badge_timer.setInterval(2_000)
        self._badge_timer.timeout.connect(self._refresh_badge)
        self._badge_timer.start()

        if hasattr(main_window, "account_state_changed"):
            main_window.account_state_changed.connect(self._rebuild_menu)

    # ---- icon ----

    def _refresh_badge(self) -> None:
        # Reload status.json — the daemon may have written to it.
        self.status_store = StatusStore()
        state = self.status_store.global_state()
        if state == self._last_state:
            return
        self._last_state = state
        self.setIcon(_compose_badge_icon("folder-cloud", state))
        if state == SyncState.SYNCING:
            self.setToolTip("Google Drive Manager — syncing…")
        elif state == SyncState.ERROR:
            self.setToolTip("Google Drive Manager — sync error (check the app)")
        else:
            self.setToolTip("Google Drive Manager — all synced")

    # ---- menu ----

    def _rebuild_menu(self) -> None:
        self._menu.clear()

        show_action = QAction("Open Google Drive Manager", self._menu)
        show_action.triggered.connect(self._show_window)
        self._menu.addAction(show_action)
        self._menu.addSeparator()

        daemon_state = "running" if daemon_active() else "stopped"
        daemon_action = QAction(f"Sync daemon: {daemon_state}", self._menu)
        if daemon_state == "stopped":
            daemon_action.setText("Start sync daemon")
            daemon_action.triggered.connect(self._start_daemon)
        else:
            daemon_action.setEnabled(False)
        self._menu.addAction(daemon_action)
        self._menu.addSeparator()

        accounts = self.store.config.accounts
        if not accounts:
            empty = QAction("No accounts configured", self._menu)
            empty.setEnabled(False)
            self._menu.addAction(empty)
        else:
            for acc in accounts:
                active = mount_active(acc.remote_name)
                sub = self._menu.addMenu(
                    f"{'🟢' if active else '⚪'} {acc.display_name}"
                )
                toggle = QAction("Unmount" if active else "Mount", sub)
                toggle.triggered.connect(lambda _=False, a=acc, on=active: self._toggle_mount(a, on))
                sub.addAction(toggle)

                if acc.pinned:
                    sub.addSeparator()
                    sync_all = QAction("Sync all pinned folders now", sub)
                    sync_all.triggered.connect(lambda _=False, a=acc: self._sync_all(a))
                    sub.addAction(sync_all)
                    for pin in acc.pinned:
                        a = QAction(f"Sync: {pin.remote_path}", sub)
                        a.triggered.connect(
                            lambda _=False, ac=acc, p=pin: run_pin_now(ac.remote_name, p)
                        )
                        sub.addAction(a)

        self._menu.addSeparator()
        quit_action = QAction("Quit", self._menu)
        quit_action.triggered.connect(QApplication.quit)
        self._menu.addAction(quit_action)

    # ---- actions ----

    def _start_daemon(self) -> None:
        try:
            start_daemon()
        except Exception as e:
            self.showMessage("Daemon error", str(e), QSystemTrayIcon.MessageIcon.Critical)
        self._rebuild_menu()

    def _toggle_mount(self, account, currently_active: bool) -> None:
        try:
            if currently_active:
                stop_mount(account.remote_name)
            else:
                start_mount(account)
        except Exception as e:
            self.showMessage("Mount error", str(e), QSystemTrayIcon.MessageIcon.Critical)
        self._rebuild_menu()

    def _sync_all(self, account) -> None:
        for pin in account.pinned:
            try:
                run_pin_now(account.remote_name, pin)
            except Exception as e:
                self.showMessage("Sync error", f"{pin.remote_path}: {e}", QSystemTrayIcon.MessageIcon.Warning)

    def _show_window(self) -> None:
        self.main_window.show()
        self.main_window.raise_()
        self.main_window.activateWindow()

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_window()
