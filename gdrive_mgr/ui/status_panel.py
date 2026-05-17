# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Account status panel: mount state, storage usage, pinned-folder summary."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from .. import rclone
from ..config import Account, ConfigStore
from ..systemd_units import mount_active


def _fmt_bytes(n: int) -> str:
    if n < 0:
        return "—"
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024:
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024
    return f"{n:.1f} PiB"


class _AboutWorker(QThread):
    done = Signal(object)

    def __init__(self, remote_name: str) -> None:
        super().__init__()
        self._remote = remote_name

    def run(self) -> None:
        try:
            usage = rclone.about(self._remote)
        except Exception:
            usage = rclone.AccountUsage()
        self.done.emit(usage)


class StatusPanel(QWidget):
    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store
        self._account: Account | None = None
        self._worker: _AboutWorker | None = None

        layout = QVBoxLayout(self)

        self.mount_group = QGroupBox("Mount")
        mount_form = QFormLayout(self.mount_group)
        self.mount_state_label = QLabel("—")
        self.mount_path_label = QLabel("—")
        mount_form.addRow("State:", self.mount_state_label)
        mount_form.addRow("Mount point:", self.mount_path_label)
        layout.addWidget(self.mount_group)

        self.usage_group = QGroupBox("Drive storage")
        usage_layout = QVBoxLayout(self.usage_group)
        self.usage_bar = QProgressBar()
        self.usage_bar.setRange(0, 100)
        self.usage_label = QLabel("—")
        usage_layout.addWidget(self.usage_bar)
        usage_layout.addWidget(self.usage_label)
        layout.addWidget(self.usage_group)

        self.pin_group = QGroupBox("Pinned (always-offline) folders")
        pin_layout = QVBoxLayout(self.pin_group)
        self.pin_summary = QLabel("No folders pinned.")
        self.pin_summary.setWordWrap(True)
        pin_layout.addWidget(self.pin_summary)
        layout.addWidget(self.pin_group)

        layout.addStretch(1)

    def set_account(self, account: Account) -> None:
        self._account = account
        self.refresh(account)

    def refresh(self, account: Account) -> None:
        if account is None:
            return
        self._account = account
        active = mount_active(account.remote_name)
        self.mount_state_label.setText(
            "🟢 Mounted" if active else "⚪ Not mounted"
        )
        self.mount_path_label.setText(account.mount_path)
        self._refresh_pin_summary(account)
        self._refresh_usage(account)

    def _refresh_pin_summary(self, account: Account) -> None:
        if not account.pinned:
            self.pin_summary.setText("No folders pinned. Use the Browse tab to pin folders for offline access.")
            return
        lines = []
        for p in account.pinned:
            status = "✓" if p.last_sync_ok else "✗"
            lines.append(f"{status} {p.remote_path}  →  {p.local_path}")
        self.pin_summary.setText("\n".join(lines))

    def _refresh_usage(self, account: Account) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self._worker = _AboutWorker(account.remote_name)
        self._worker.done.connect(self._on_usage)
        self._worker.start()

    def _on_usage(self, usage: rclone.AccountUsage) -> None:
        if usage.total_bytes > 0:
            pct = int(100 * usage.used_bytes / usage.total_bytes)
            self.usage_bar.setValue(pct)
            self.usage_label.setText(
                f"{_fmt_bytes(usage.used_bytes)} of {_fmt_bytes(usage.total_bytes)} used"
                f" ({pct}%)"
            )
        else:
            self.usage_bar.setValue(0)
            self.usage_label.setText("Usage info unavailable.")
