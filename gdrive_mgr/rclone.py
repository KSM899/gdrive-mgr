# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Khalid Said
"""Thin subprocess wrapper around the `rclone` CLI.

Everything runs as the current user. We never call interactive `rclone config`
— for OAuth we use `rclone authorize "drive"` which prints a JSON token blob
to stdout that we then materialize via `rclone config create`.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Iterator


class RcloneError(RuntimeError):
    pass


def rclone_path() -> str:
    p = shutil.which("rclone")
    if not p:
        raise RcloneError("rclone not found on PATH; install with `sudo dnf install rclone`")
    return p


def _run(
    args: list[str],
    *,
    input_text: str | None = None,
    timeout: float | None = 120.0,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [rclone_path(), *args]
    try:
        proc = subprocess.run(
            cmd,
            input=input_text,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise RcloneError(f"rclone {args[0] if args else '?'} timed out after {e.timeout}s") from e
    if check and proc.returncode != 0:
        raise RcloneError(
            f"rclone {' '.join(args)} failed (exit {proc.returncode}):\n{proc.stderr.strip()}"
        )
    return proc


def version() -> str:
    out = _run(["version"]).stdout
    first = out.splitlines()[0] if out else ""
    return first.strip()


def list_remotes() -> list[str]:
    """Return rclone-configured remote names (without trailing ':')."""
    out = _run(["listremotes"]).stdout
    return [line.rstrip(":") for line in out.splitlines() if line.strip()]


def remote_type(remote: str) -> str:
    """Return the storage type for a configured remote (e.g. 'drive')."""
    out = _run(["config", "show", remote]).stdout
    for line in out.splitlines():
        if line.strip().startswith("type"):
            _, _, value = line.partition("=")
            return value.strip()
    return ""


@dataclass
class DriveEntry:
    name: str
    path: str               # path relative to remote root, no leading slash
    is_dir: bool
    size: int               # -1 for unknown / folders
    mime_type: str = ""
    modified_iso: str = ""

    def child_path(self, child_name: str) -> str:
        if not self.path:
            return child_name
        return f"{self.path}/{child_name}"


def lsjson(remote: str, path: str = "", *, dirs_only: bool = False) -> list[DriveEntry]:
    """List one level under remote:path. Returns folders first, then files, alphabetical."""
    target = f"{remote}:{path}" if path else f"{remote}:"
    args = ["lsjson", target, "--no-modtime" if False else "--fast-list"]
    if dirs_only:
        args.append("--dirs-only")
    proc = _run(args, timeout=60.0)
    raw = json.loads(proc.stdout or "[]")
    entries: list[DriveEntry] = []
    for item in raw:
        name = item.get("Name", "")
        if not name:
            continue
        rel_path = f"{path}/{name}" if path else name
        entries.append(
            DriveEntry(
                name=name,
                path=rel_path,
                is_dir=bool(item.get("IsDir", False)),
                size=int(item.get("Size", -1)),
                mime_type=item.get("MimeType", ""),
                modified_iso=item.get("ModTime", ""),
            )
        )
    entries.sort(key=lambda e: (not e.is_dir, e.name.lower()))
    return entries


@dataclass
class AccountUsage:
    used_bytes: int = -1
    total_bytes: int = -1
    trashed_bytes: int = -1
    free_bytes: int = -1


def about(remote: str) -> AccountUsage:
    proc = _run(["about", f"{remote}:", "--json"], timeout=30.0, check=False)
    if proc.returncode != 0:
        return AccountUsage()
    data = json.loads(proc.stdout or "{}")
    return AccountUsage(
        used_bytes=int(data.get("used", -1)),
        total_bytes=int(data.get("total", -1)),
        trashed_bytes=int(data.get("trashed", -1)),
        free_bytes=int(data.get("free", -1)),
    )


def authorize_drive() -> Iterator[tuple[str, str]]:
    """Run `rclone authorize "drive"` and stream stdout as (kind, line) tuples.

    Kinds:
      - 'url'   the local-callback OAuth URL (or accounts.google.com URL)
      - 'info'  status lines (NOTICEs, etc.) — safe to display
      - 'token' the JSON token blob (yielded once at the end)

    rclone authorize starts a local HTTP listener, opens a browser to Google's
    OAuth screen, waits for the redirect, then prints the token between two
    sentinel lines:

        Paste the following into your remote machine --->
        {
            "access_token": "...",
            "refresh_token": "...",
            ...
        }
        <---End paste

    We stream info lines as they arrive (so the wizard log stays live), but we
    suppress lines while inside the paste block so the token itself never hits
    the UI. After the subprocess exits we regex-extract the JSON object and
    yield it as ('token', json_string).
    """
    cmd = [rclone_path(), "authorize", "drive"]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None

    all_output: list[str] = []
    in_paste = False
    try:
        for raw in proc.stdout:
            line = raw.rstrip("\n")
            all_output.append(line)

            if "Paste the following" in line:
                in_paste = True
                continue
            if "End paste" in line:
                in_paste = False
                continue
            if in_paste:
                continue

            url_match = re.search(
                r"https?://(?:127\.0\.0\.1|accounts\.google\.com)\S*",
                line,
            )
            if url_match:
                yield ("url", url_match.group(0))
                continue

            yield ("info", line)
    finally:
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    full = "\n".join(all_output)

    block = re.search(r"--->\s*\n(.*?)\n<---End paste", full, re.DOTALL)
    if block:
        candidate = block.group(1).strip()
        try:
            json.loads(candidate)
            yield ("token", candidate)
            return
        except json.JSONDecodeError:
            pass

    for m in re.finditer(r"\{[^{}]*\"access_token\"[^{}]*\}", full, re.DOTALL):
        candidate = m.group(0)
        try:
            json.loads(candidate)
            yield ("token", candidate)
            return
        except json.JSONDecodeError:
            continue


def config_create_drive(remote_name: str, token_json: str) -> None:
    """Create a Google Drive remote from a prefetched OAuth token JSON."""
    args = [
        "config", "create", remote_name, "drive",
        "scope", "drive",
        "token", token_json,
        "config_is_local", "false",
    ]
    _run(args, timeout=30.0)


def create_drive_remote(remote_name: str) -> Iterator[tuple[str, str]]:
    """Run `rclone config create <name> drive scope=drive` end-to-end.

    Unlike `authorize_drive` + `config_create_drive`, this single command lets
    rclone handle the OAuth flow internally: it opens a browser, runs the local
    HTTP listener for the redirect, and writes the new remote to the rclone
    config on success — no token parsing needed.

    Yields:
      - ('url', url)      OAuth URL (also opened in browser automatically)
      - ('info', line)    every other log line
      - ('success', '')   process exited 0 (remote was created)
      - ('error', tail)   process exited non-zero; tail is last ~80 lines
    """
    cmd = [
        rclone_path(),
        "config", "create", remote_name, "drive",
        "scope", "drive",
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    assert proc.stdout is not None

    tail: list[str] = []
    url_seen = False
    # Only match the actual Google OAuth consent URL. rclone prints a setup
    # hint mentioning the local callback URL (http://127.0.0.1:PORT/) in
    # quotes before that, which we must NOT capture as the URL to open.
    oauth_url_re = re.compile(r"https://accounts\.google\.com/[^\s\"'<>)]+")
    for raw in proc.stdout:
        line = raw.rstrip("\n")
        tail.append(line)
        if len(tail) > 80:
            tail = tail[-80:]
        if not url_seen:
            m = oauth_url_re.search(line)
            if m:
                url_seen = True
                yield ("url", m.group(0))
                continue
        yield ("info", line)

    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        yield ("error", "rclone config create timed out")
        return

    if proc.returncode == 0:
        yield ("success", "")
    else:
        yield ("error", "\n".join(tail))


def config_delete(remote_name: str) -> None:
    _run(["config", "delete", remote_name], check=False)


def bisync(
    remote: str,
    remote_path: str,
    local_path: str,
    *,
    resync: bool = False,
    extra: list[str] | None = None,
) -> tuple[bool, str]:
    """Run rclone bisync. Returns (ok, combined_stderr_output).

    bisync is marked beta upstream; we use --resilient and --conflict-suffix
    to make conflict files easy to spot in the UI.
    """
    src = f"{remote}:{remote_path}" if remote_path else f"{remote}:"
    args = [
        "bisync", src, local_path,
        "--resilient",
        "--conflict-resolve", "newer",
        "--conflict-loser", "num",
        "--conflict-suffix", "conflict",
        "--create-empty-src-dirs",
    ]
    if resync:
        args.append("--resync")
    if extra:
        args.extend(extra)
    proc = _run(args, timeout=None, check=False)
    return proc.returncode == 0, (proc.stderr or "") + (proc.stdout or "")


def stat_file(remote: str, remote_path: str) -> DriveEntry | None:
    """Return metadata for a single file in the remote. None if it doesn't exist.

    We use lsjson on the file's parent directory and filter by name — there's
    no single-file 'stat' subcommand in rclone, but this is cheap enough at
    file-level sync frequency."""
    from pathlib import PurePosixPath
    p = PurePosixPath(remote_path)
    parent = str(p.parent) if str(p.parent) != "." else ""
    name = p.name
    try:
        entries = lsjson(remote, parent, dirs_only=False)
    except RcloneError:
        return None
    for e in entries:
        if e.name == name and not e.is_dir:
            return e
    return None


def copyto(src: str, dst: str, *, extra: list[str] | None = None) -> tuple[bool, str]:
    """Copy a single file from src to dst. Either side may be a remote
    (e.g. 'gdrive:Folder/file.txt') or a local absolute path.

    `rclone copyto` overwrites the destination by default, which is what we
    want for per-file pin sync — the higher-level worker decides which side
    to overwrite based on which one changed.
    """
    args = ["copyto", src, dst]
    if extra:
        args.extend(extra)
    proc = _run(args, timeout=None, check=False)
    return proc.returncode == 0, (proc.stderr or "") + (proc.stdout or "")


def share_link(remote: str, remote_path: str) -> str:
    """Generate or fetch a public share link for a file/folder on Drive.

    This is `rclone link`, which on the Drive backend grants 'anyone with the
    link' viewer access and returns the public URL. Returns the URL string.
    Raises RcloneError on failure (e.g. unsupported by backend, network).
    """
    target = f"{remote}:{remote_path}" if remote_path else f"{remote}:"
    proc = _run(["link", target], timeout=30.0)
    url = (proc.stdout or "").strip()
    if not url.startswith("http"):
        raise RcloneError(f"rclone link returned no URL: {proc.stdout!r} / {proc.stderr!r}")
    return url


def file_id(remote: str, remote_path: str) -> str | None:
    """Return the Drive file/folder ID for the given path, or None if not found.

    Uses lsjson on the parent dir and matches by name. The ID is what
    Drive's web UI uses in URLs like https://drive.google.com/open?id=<ID>.
    """
    from pathlib import PurePosixPath
    p = PurePosixPath(remote_path)
    parent = str(p.parent) if str(p.parent) != "." else ""
    name = p.name
    try:
        entries = _run(["lsjson", f"{remote}:{parent}" if parent else f"{remote}:"], timeout=30.0)
    except RcloneError:
        return None
    items = json.loads(entries.stdout or "[]")
    for item in items:
        if item.get("Name") == name:
            return item.get("ID") or None
    return None


def find_conflicts(local_path: str) -> list[str]:
    """Return absolute paths of bisync conflict files under local_path."""
    import pathlib
    base = pathlib.Path(local_path)
    if not base.exists():
        return []
    return [str(p) for p in base.rglob("*.conflict*")]
