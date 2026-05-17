# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Generate and control systemd --user units for mounts and bisync timers.

Two unit families:
- gdrive-mount@<remote>.service — runs rclone mount for one account
- gdrive-pin@<remote>--<slug>.service + .timer — periodic bisync for one pinned folder

We use templated unit names so we can manage many accounts/folders without
re-writing files. The template files themselves are static; we only write them
once per app version.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import Account, PinnedFolder

UNIT_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")) / "gdrive-mgr"


MOUNT_UNIT_NAME = "gdrive-mount@.service"
PIN_SERVICE_NAME = "gdrive-pin@.service"
PIN_TIMER_NAME = "gdrive-pin@.timer"
DAEMON_UNIT_NAME = "gdrive-mgr-daemon.service"


def _rclone_bin() -> str:
    p = shutil.which("rclone")
    if not p:
        raise RuntimeError("rclone not on PATH")
    return p


def ensure_template_units() -> None:
    """Install the templated unit files. Idempotent."""
    UNIT_DIR.mkdir(parents=True, exist_ok=True)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    rclone = _rclone_bin()

    mount_unit = f"""[Unit]
Description=rclone mount for Google Drive remote %i
AssertPathIsDirectory=%h/GoogleDrive/%i
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
ExecStart={rclone} mount %i: %h/GoogleDrive/%i \\
  --vfs-cache-mode full \\
  --vfs-cache-max-size 10G \\
  --vfs-cache-max-age 24h \\
  --vfs-write-back 1s \\
  --vfs-fast-fingerprint \\
  --dir-cache-time 1h \\
  --poll-interval 15s \\
  --drive-pacer-min-sleep 10ms \\
  --drive-pacer-burst 200 \\
  --no-checksum \\
  --exclude .~lock.*# \\
  --exclude .~lock.* \\
  --exclude *.tmp \\
  --umask 022
ExecStop=/bin/fusermount3 -u %h/GoogleDrive/%i
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""

    # Use the same Python interpreter we're running under — this is the venv's
    # python in normal use, which has gdrive_mgr importable. Pinning to the
    # project dir as WorkingDirectory makes sure relative imports also work
    # when the service runs outside the user's interactive session.
    py = sys.executable
    project_dir = str(Path(__file__).resolve().parent.parent)
    pin_service = f"""[Unit]
Description=gdrive-mgr bisync for %i
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory={project_dir}
Environment=PYTHONPATH={project_dir}
ExecStart={py} -m gdrive_mgr.cli bisync-instance %i
StandardOutput=journal
StandardError=journal
"""

    pin_timer = """[Unit]
Description=gdrive-mgr periodic bisync for %i

[Timer]
OnBootSec=2min
OnUnitActiveSec=15min
Persistent=true
Unit=gdrive-pin@%i.service

[Install]
WantedBy=timers.target
"""

    daemon_unit = f"""[Unit]
Description=gdrive-mgr inotify + sync daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory={project_dir}
Environment=PYTHONPATH={project_dir}
ExecStart={py} -m gdrive_mgr.cli daemon
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
"""

    _write_if_changed(UNIT_DIR / MOUNT_UNIT_NAME, mount_unit)
    _write_if_changed(UNIT_DIR / PIN_SERVICE_NAME, pin_service)
    _write_if_changed(UNIT_DIR / PIN_TIMER_NAME, pin_timer)
    _write_if_changed(UNIT_DIR / DAEMON_UNIT_NAME, daemon_unit)
    daemon_reload()


def start_daemon() -> None:
    _systemctl("enable", "--now", DAEMON_UNIT_NAME)


def stop_daemon() -> None:
    _systemctl("disable", "--now", DAEMON_UNIT_NAME, check=False)


def daemon_active() -> bool:
    proc = _systemctl("is-active", DAEMON_UNIT_NAME, check=False)
    return proc.stdout.strip() == "active"


def _write_if_changed(path: Path, content: str) -> None:
    if path.exists() and path.read_text() == content:
        return
    path.write_text(content)


def _systemctl(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    cmd = ["systemctl", "--user", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"systemctl {' '.join(args)} failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return proc


def daemon_reload() -> None:
    _systemctl("daemon-reload")


# ---- mount control ----

def mount_unit_instance(remote_name: str) -> str:
    return f"gdrive-mount@{remote_name}.service"


def start_mount(account: Account) -> None:
    Path(account.mount_path).mkdir(parents=True, exist_ok=True)
    _systemctl("enable", "--now", mount_unit_instance(account.remote_name))


def stop_mount(remote_name: str) -> None:
    _systemctl("disable", "--now", mount_unit_instance(remote_name), check=False)


def mount_active(remote_name: str) -> bool:
    proc = _systemctl("is-active", mount_unit_instance(remote_name), check=False)
    return proc.stdout.strip() == "active"


# ---- pin control ----

def _pin_instance(remote_name: str, pin: PinnedFolder) -> str:
    """Returns the systemd instance name for a (remote, pin) pair, e.g.
    gdrive-personal--Work-Projects
    The double-dash separates remote from path slug.
    """
    return f"{remote_name}--{pin.unit_slug()}"


def pin_service_unit(remote_name: str, pin: PinnedFolder) -> str:
    return f"gdrive-pin@{_pin_instance(remote_name, pin)}.service"


def pin_timer_unit(remote_name: str, pin: PinnedFolder) -> str:
    return f"gdrive-pin@{_pin_instance(remote_name, pin)}.timer"


def enable_pin(remote_name: str, pin: PinnedFolder) -> None:
    Path(pin.local_path).mkdir(parents=True, exist_ok=True)
    _systemctl("enable", "--now", pin_timer_unit(remote_name, pin))


def disable_pin(remote_name: str, pin: PinnedFolder) -> None:
    _systemctl("disable", "--now", pin_timer_unit(remote_name, pin), check=False)
    _systemctl("stop", pin_service_unit(remote_name, pin), check=False)


def run_pin_now(remote_name: str, pin: PinnedFolder) -> None:
    _systemctl("start", pin_service_unit(remote_name, pin))


def pin_last_status(remote_name: str, pin: PinnedFolder) -> str:
    proc = _systemctl(
        "show",
        pin_service_unit(remote_name, pin),
        "--property=Result,ActiveState,ExecMainStatus",
        check=False,
    )
    return proc.stdout.strip()


# ---- locator helpers for the CLI invoked by the unit ----

def parse_pin_instance(instance: str) -> tuple[str, str]:
    """Inverse of _pin_instance: split 'remote--path-slug' back into (remote, slug)."""
    remote, _, slug = instance.partition("--")
    return remote, slug
