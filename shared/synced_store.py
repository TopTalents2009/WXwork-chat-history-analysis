"""Store chat records pushed from remote WeCom sync agents."""
import importlib.util
import json
import os
import re
import socket
from datetime import datetime
from typing import List, Optional


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYNCED_ROOT = os.path.join(PROJECT_ROOT, "export", "synced")


def _safe_id(value: str) -> str:
    text = re.sub(r"[^\w.\-]+", "_", str(value or "").strip())
    return (text or "pc")[:80]


def source_id_for(computer_name: str, account_id: str = "") -> str:
    return _safe_id(f"{computer_name}-{account_id}" if account_id else computer_name)


def find_source_id(computer_name: str = "", account_id: str = "", host: str = "") -> str:
    """Reuse an existing synced folder when the agent has no account_id yet."""
    account_id = str(account_id or "").strip()
    computer_name = (computer_name or "").strip()
    host = (host or "").strip()
    if account_id:
        return source_id_for(computer_name, account_id)
    for src in list_sources():
        if computer_name and (src.get("computer_name") or "") == computer_name:
            return src["id"]
        if host and (src.get("host") or "") == host:
            return src["id"]
    return source_id_for(computer_name, account_id)


def _message_key(item: dict) -> str:
    mid = int(item.get("message_id") or 0)
    if mid:
        return f"id:{mid}"
    text = str(item.get("text") or "")[:80]
    return f"t:{item.get('time_text') or ''}|{item.get('sender') or ''}|{text}"


def merge_messages(old: list, new: list) -> list:
    """Keep the union of old and new messages; the latest payload wins on id clash."""
    by_key = {}
    order = []
    for item in list(old or []) + list(new or []):
        if not isinstance(item, dict):
            continue
        key = _message_key(item)
        if key in by_key:
            by_key[key] = item
            continue
        order.append(key)
        by_key[key] = item
    merged = [by_key[key] for key in order]
    merged.sort(key=lambda m: (str(m.get("time_text") or ""), int(m.get("message_id") or 0)))
    return merged


def _source_dir(source_id: str) -> str:
    return os.path.join(SYNCED_ROOT, _safe_id(source_id))


def _read_json(path: str, default):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def list_sources() -> List[dict]:
    os.makedirs(SYNCED_ROOT, exist_ok=True)
    sources = []
    for name in sorted(os.listdir(SYNCED_ROOT)):
        meta_path = os.path.join(SYNCED_ROOT, name, "meta.json")
        if not os.path.isfile(meta_path):
            continue
        meta = _read_json(meta_path, {})
        sessions = _read_json(os.path.join(SYNCED_ROOT, name, "sessions.json"), [])
        sources.append({
            "id": name,
            "kind": "remote",
            "computer_name": meta.get("computer_name") or name,
            "operator_name": meta.get("operator_name") or "",
            "username": meta.get("username") or "",
            "account_id": meta.get("account_id") or "",
            "host": meta.get("host") or "",
            "last_sync": meta.get("last_sync") or "",
            "session_count": len(sessions),
            "platform": "wecom",
        })
    sources.sort(key=lambda s: s.get("last_sync") or "", reverse=True)
    return sources


def save_ingest(payload: dict) -> dict:
    computer_name = (payload.get("computer_name") or socket.gethostname()).strip()
    account_id = str(payload.get("account_id") or "")
    operator_name = (
        payload.get("operator_name")
        or payload.get("display_name")
        or ""
    ).strip()
    source_id = payload.get("source_id") or source_id_for(computer_name, account_id)
    source_id = _safe_id(source_id)
    folder = _source_dir(source_id)
    os.makedirs(folder, exist_ok=True)
    old_meta = _read_json(os.path.join(folder, "meta.json"), {})
    if not operator_name:
        operator_name = (old_meta.get("operator_name") or "").strip()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sync_seq = int(old_meta.get("sync_seq") or 0) + 1

    incoming = payload.get("sessions") or []
    existing_sessions = {
        s["username"]: s
        for s in _read_json(os.path.join(folder, "sessions.json"), [])
        if s.get("username")
    }
    saved = 0
    for item in incoming:
        sid = str(item.get("id") or item.get("username") or "")
        if not sid:
            continue
        messages_path = os.path.join(folder, "messages", _safe_id(sid) + ".json")
        incoming_messages = [_sanitize_stored_message(m) for m in (item.get("messages") or [])]
        existing_messages = _read_json(messages_path, [])
        messages = merge_messages(existing_messages, incoming_messages)
        _write_json(messages_path, messages)
        existing_sessions[sid] = {
            "username": sid,
            "display_name": item.get("display_name") or sid,
            "session_type": int(item.get("session_type") or 0),
            "last_time": item.get("last_time") or "",
            "msg_count": len(messages),
            "summary": item.get("summary") or "",
            "synced_at": now,
            "sync_seq": sync_seq,
        }
        saved += 1

    sessions = list(existing_sessions.values())
    sessions.sort(
        key=lambda s: (int(s.get("sync_seq") or 0), s.get("synced_at") or "", s.get("last_time") or ""),
        reverse=True,
    )
    _write_json(os.path.join(folder, "sessions.json"), sessions)

    meta = {
        "id": source_id,
        "computer_name": computer_name,
        "operator_name": operator_name,
        "username": payload.get("username") or operator_name,
        "account_id": account_id,
        "host": payload.get("host") or "",
        "last_sync": now,
        "sync_seq": sync_seq,
        "platform": "wecom",
    }
    _write_json(os.path.join(folder, "meta.json"), meta)
    return {
        "source_id": source_id,
        "computer_name": computer_name,
        "operator_name": operator_name,
        "saved_sessions": saved,
        "session_count": len(sessions),
        "last_sync": meta["last_sync"],
    }


def get_source(source_id: str) -> Optional[dict]:
    meta_path = os.path.join(_source_dir(source_id), "meta.json")
    if not os.path.isfile(meta_path):
        return None
    meta = _read_json(meta_path, {})
    sessions = _read_json(os.path.join(_source_dir(source_id), "sessions.json"), [])
    meta["id"] = source_id
    meta["session_count"] = len(sessions)
    meta["kind"] = "local" if source_id == "local" else "remote"
    return meta


def list_sessions(source_id: str) -> List[dict]:
    sessions = _read_json(os.path.join(_source_dir(source_id), "sessions.json"), [])
    sessions.sort(
        key=lambda s: (int(s.get("sync_seq") or 0), s.get("synced_at") or "", s.get("last_time") or ""),
        reverse=True,
    )
    return sessions


def list_messages(source_id: str, session_id: str, limit: int = 1000) -> List[dict]:
    path = os.path.join(_source_dir(source_id), "messages", _safe_id(session_id) + ".json")
    messages = _read_json(path, [])
    changed = False
    cleaned = []
    for item in messages:
        new_item = _sanitize_stored_message(item)
        if (
            new_item.get("text") != item.get("text")
            or new_item.get("media_url") != item.get("media_url")
            or new_item.get("attachment_name") != item.get("attachment_name")
        ):
            changed = True
        cleaned.append(new_item)
    if changed:
        _write_json(path, cleaned)
        messages = cleaned
    if not limit or int(limit) <= 0:
        return messages
    if len(messages) > int(limit):
        return messages[-int(limit):]
    return messages


def get_message(source_id: str, session_id: str, message_id: int) -> Optional[dict]:
    for item in list_messages(source_id, session_id, limit=0):
        if int(item.get("message_id") or 0) == int(message_id):
            return item
    return None


_decode_mod = None


def _decoder():
    global _decode_mod
    if _decode_mod is None:
        decode_path = os.path.join(PROJECT_ROOT, "core-wecom", "message_decode.py")
        spec = importlib.util.spec_from_file_location("wecom_message_decode", decode_path)
        _decode_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(_decode_mod)
    return _decode_mod


def _sanitize_stored_message(item: dict) -> dict:
    out = dict(item)
    text, media_url, name = _decoder().recover_display_fields(
        out.get("msg_type"),
        out.get("text"),
        out.get("media_url") or "",
        out.get("attachment_name") or "",
    )
    out["text"] = text
    out["media_url"] = media_url
    out["attachment_name"] = name
    if media_url or name:
        out["has_attachment"] = True
    return out
