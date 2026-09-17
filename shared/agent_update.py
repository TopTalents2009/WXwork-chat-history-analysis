"""Publish the packaged WeCom sync agent for client self-update."""
import hashlib
import os
import re
from typing import List, Optional


_CACHE = {"path": "", "mtime": 0.0, "size": 0, "sha256": ""}
_CHANGELOG_HEADING = re.compile(r"^##\s+(\S+)")
_CHANGELOG_BULLET = re.compile(r"^[-*]\s+(.+)$")


def version_path(project_root: str) -> str:
    return os.path.join(project_root, "agent", "VERSION")


def changelog_path(project_root: str) -> str:
    return os.path.join(project_root, "agent", "CHANGELOG.md")


def agent_exe_path(project_root: str) -> str:
    path = os.path.join(project_root, "dist", "WeComSyncAgent.exe")
    return path if os.path.isfile(path) else ""


def read_version(project_root: str) -> str:
    path = version_path(project_root)
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, encoding="utf-8") as f:
            return (f.read() or "").strip()
    except OSError:
        return ""


def parse_changelog(text: str) -> List[dict]:
    entries: List[dict] = []
    current = None
    for raw in (text or "").splitlines():
        heading = _CHANGELOG_HEADING.match(raw.strip())
        if heading:
            current = {"version": heading.group(1).strip(), "notes": []}
            entries.append(current)
            continue
        if current is None:
            continue
        bullet = _CHANGELOG_BULLET.match(raw.strip())
        if bullet:
            note = bullet.group(1).strip()
            if note:
                current["notes"].append(note)
    return entries


def read_changelog(project_root: str) -> List[dict]:
    path = changelog_path(project_root)
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return parse_changelog(f.read())
    except OSError:
        return []


def notes_for_version(entries: List[dict], version: str) -> List[str]:
    version = (version or "").strip()
    for item in entries:
        if item.get("version") == version:
            return list(item.get("notes") or [])
    return []


def hash_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _cached_hash(path: str) -> str:
    st = os.stat(path)
    if (
        _CACHE["path"] == path
        and _CACHE["mtime"] == st.st_mtime
        and _CACHE["size"] == st.st_size
        and _CACHE["sha256"]
    ):
        return _CACHE["sha256"]
    sha256 = hash_file(path)
    _CACHE.update({
        "path": path,
        "mtime": st.st_mtime,
        "size": st.st_size,
        "sha256": sha256,
    })
    return sha256


def build_manifest(project_root: str) -> Optional[dict]:
    version = read_version(project_root)
    path = agent_exe_path(project_root)
    if not version or not path:
        return None
    st = os.stat(path)
    entries = read_changelog(project_root)
    notes = notes_for_version(entries, version)
    return {
        "version": version,
        "sha256": _cached_hash(path),
        "size": int(st.st_size),
        "url": "/api/ingest/agent-exe",
        "notes": "\n".join(notes),
        "changelog": entries[:12],
    }
