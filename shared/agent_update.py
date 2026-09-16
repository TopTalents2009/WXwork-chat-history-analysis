"""Publish the packaged WeCom sync agent for client self-update."""
import hashlib
import os
from typing import Optional


_CACHE = {"path": "", "mtime": 0.0, "size": 0, "sha256": ""}


def version_path(project_root: str) -> str:
    return os.path.join(project_root, "agent", "VERSION")


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
    return {
        "version": version,
        "sha256": _cached_hash(path),
        "size": int(st.st_size),
        "url": "/api/ingest/agent-exe",
    }
