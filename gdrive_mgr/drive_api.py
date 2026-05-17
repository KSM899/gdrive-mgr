# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Thin wrapper around Google Drive v3 permissions API.

We reuse rclone's already-authorized OAuth token instead of running our own
consent flow — extract the token from rclone's config, refresh on demand
against Google's OAuth endpoint, and call the Drive REST API directly with
urllib (no extra pip deps).

Used by the in-app Share dialog. The shell-only flows (rclone link, etc.)
in cli.py do not depend on this module.
"""

from __future__ import annotations

import json
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

# rclone's built-in OAuth client for Google Drive. Public credentials, baked
# into rclone's open-source repo. If the user has overridden these in their
# rclone config (custom client_id/secret) we'll pick those up at load time.
_RCLONE_DRIVE_CLIENT_ID = "202264815644.apps.googleusercontent.com"
_RCLONE_DRIVE_CLIENT_SECRET = "X4Z3ca8xfWDb1Voo-F9a7ZxJ"

TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://www.googleapis.com/drive/v3"


class DriveAPIError(RuntimeError):
    """Raised when the Drive API returns an error or auth fails."""


@dataclass
class _Token:
    access_token: str
    refresh_token: str
    expiry_ts: float
    client_id: str
    client_secret: str


def _parse_expiry(iso: str) -> float:
    if not iso:
        return 0.0
    try:
        # rclone may emit fractional seconds with nanosecond precision and
        # a timezone like '+04:00'. datetime.fromisoformat (3.11+) handles
        # both — we additionally strip a trailing 'Z' for safety.
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _load_token(remote_name: str) -> _Token:
    try:
        proc = subprocess.run(
            ["rclone", "config", "show", remote_name],
            capture_output=True, text=True, check=True, timeout=10,
        )
    except subprocess.CalledProcessError as e:
        raise DriveAPIError(f"rclone config show failed: {e.stderr.strip()}") from e

    token_json = ""
    client_id = _RCLONE_DRIVE_CLIENT_ID
    client_secret = _RCLONE_DRIVE_CLIENT_SECRET
    for raw in proc.stdout.splitlines():
        line = raw.strip()
        if line.startswith("token = "):
            token_json = line[len("token = "):]
        elif line.startswith("client_id = ") and line[len("client_id = "):].strip():
            client_id = line[len("client_id = "):].strip()
        elif line.startswith("client_secret = ") and line[len("client_secret = "):].strip():
            client_secret = line[len("client_secret = "):].strip()

    if not token_json:
        raise DriveAPIError(f"no OAuth token found for rclone remote {remote_name!r}")

    try:
        td = json.loads(token_json)
    except json.JSONDecodeError as e:
        raise DriveAPIError(f"token JSON in rclone config is malformed: {e}") from e

    return _Token(
        access_token=td.get("access_token", ""),
        refresh_token=td.get("refresh_token", ""),
        expiry_ts=_parse_expiry(td.get("expiry", "")),
        client_id=client_id,
        client_secret=client_secret,
    )


def _refresh_if_needed(token: _Token) -> None:
    if token.expiry_ts and token.expiry_ts > time.time() + 60:
        return
    if not token.refresh_token:
        raise DriveAPIError("access token expired and no refresh_token available")

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": token.refresh_token,
        "client_id": token.client_id,
        "client_secret": token.client_secret,
    }).encode("utf-8")
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")
        raise DriveAPIError(f"OAuth refresh returned {e.code}: {msg}") from e

    token.access_token = data["access_token"]
    token.expiry_ts = time.time() + int(data.get("expires_in", 3600))


def _api(token: _Token, method: str, path: str, *, body: dict | None = None, params: dict | None = None) -> dict | None:
    _refresh_if_needed(token)
    url = API_ROOT + path
    if params:
        # Drop None values so callers can pass conditional params cleanly.
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token.access_token}")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            if not raw:
                return None
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise DriveAPIError(f"Drive API {method} {path} → HTTP {e.code}: {detail}") from e


# ---- public API ----

def list_permissions(remote_name: str, file_id: str) -> list[dict]:
    token = _load_token(remote_name)
    result = _api(
        token, "GET", f"/files/{file_id}/permissions",
        params={
            "fields": "permissions(id,emailAddress,role,type,displayName,domain,deleted)",
            "supportsAllDrives": "true",
        },
    )
    return (result or {}).get("permissions", [])


def add_permission(
    remote_name: str,
    file_id: str,
    email: str,
    role: str,
    *,
    notify: bool = True,
    message: str = "",
) -> dict:
    """Grant `email` access at `role` (reader/commenter/writer)."""
    if role not in ("reader", "commenter", "writer"):
        raise ValueError(f"invalid role: {role!r}")
    token = _load_token(remote_name)
    body = {"type": "user", "role": role, "emailAddress": email}
    params: dict[str, str | None] = {
        "sendNotificationEmail": "true" if notify else "false",
        "fields": "id,emailAddress,role,type",
        "supportsAllDrives": "true",
    }
    if notify and message:
        params["emailMessage"] = message
    result = _api(token, "POST", f"/files/{file_id}/permissions", body=body, params=params)
    return result or {}


def remove_permission(remote_name: str, file_id: str, permission_id: str) -> None:
    token = _load_token(remote_name)
    _api(
        token, "DELETE", f"/files/{file_id}/permissions/{permission_id}",
        params={"supportsAllDrives": "true"},
    )
