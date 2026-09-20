"""Search decoded WeCom chat messages on the server."""
import os
from typing import List

from shared import synced_store


def tokenize(query: str) -> List[str]:
    parts = []
    for item in str(query or "").replace("\u3000", " ").split():
        text = item.strip().casefold()
        if text:
            parts.append(text)
    return parts[:8]


def haystack_for(item: dict, session_name: str = "") -> str:
    parts = [
        item.get("text") or "",
        item.get("sender") or "",
        item.get("attachment_name") or "",
        session_name or "",
    ]
    return "\n".join(parts).casefold()


def matches(haystack: str, tokens: List[str]) -> bool:
    if not tokens:
        return False
    return all(token in haystack for token in tokens)


def snippet(text: str, tokens: List[str], radius: int = 36) -> str:
    raw = (text or "").replace("\n", " ").strip()
    if not raw:
        return ""
    lowered = raw.casefold()
    idx = -1
    width = 0
    for token in tokens:
        found = lowered.find(token)
        if found >= 0:
            idx = found
            width = len(token)
            break
    if idx < 0:
        return raw[:80]
    start = max(0, idx - radius)
    end = min(len(raw), idx + width + radius)
    prefix = "…" if start else ""
    suffix = "…" if end < len(raw) else ""
    return prefix + raw[start:end] + suffix


def _hit(source_id: str, source_name: str, session_id: str, session_name: str, item: dict, tokens: List[str]) -> dict:
    text = item.get("text") or ""
    return {
        "source_id": source_id,
        "source_name": source_name,
        "session_id": session_id,
        "session_name": session_name or session_id,
        "time_text": item.get("time_text") or "",
        "sender": item.get("sender") or "",
        "sender_id": item.get("sender_id") or "",
        "text": text,
        "snippet": snippet(text, tokens) or snippet(item.get("attachment_name") or "", tokens),
        "message_id": int(item.get("message_id") or 0),
        "msg_type": int(item.get("msg_type") or 0),
        "attachment_name": item.get("attachment_name") or "",
        "media_url": item.get("media_url") or "",
    }


def search_synced(
    source_id: str,
    tokens: List[str],
    session_id: str = "",
    limit: int = 50,
) -> List[dict]:
    source = synced_store.get_source(source_id) or {}
    source_name = source.get("operator_name") or source.get("computer_name") or source_id
    hits = []
    for session in synced_store.list_sessions(source_id):
        sid = str(session.get("username") or "")
        if not sid:
            continue
        if session_id and sid != session_id:
            continue
        name = session.get("display_name") or sid
        path = os.path.join(
            synced_store._source_dir(source_id),
            "messages",
            synced_store._safe_id(sid) + ".json",
        )
        for item in synced_store._read_json(path, []):
            if not matches(haystack_for(item, name), tokens):
                continue
            hits.append(_hit(source_id, source_name, sid, name, item, tokens))
    hits.sort(key=lambda row: row.get("time_text") or "", reverse=True)
    return hits[:limit]


def search_local(
    platform,
    tokens: List[str],
    session_id: str = "",
    limit: int = 50,
    source_id: str = "local",
    source_name: str = "本机",
) -> List[dict]:
    hits = []
    sessions = platform.list_sessions(limit=2000)
    msg_limit = 4000 if session_id else 1200
    for session in sessions:
        sid = session.username
        if session_id and sid != session_id:
            continue
        name = session.display_name or sid
        for msg in platform.query_messages(sid, limit=msg_limit):
            item = {
                "time_text": msg.time.strftime("%Y-%m-%d %H:%M") if msg.time else (msg.time_text or ""),
                "sender": msg.sender,
                "sender_id": msg.sender_id,
                "text": msg.text,
                "message_id": msg.message_id,
                "msg_type": msg.msg_type,
                "attachment_name": msg.attachment_name,
                "media_url": getattr(msg, "media_url", "") or "",
            }
            if matches(haystack_for(item, name), tokens):
                hits.append(_hit(source_id, source_name, sid, name, item, tokens))
        if session_id:
            break
    hits.sort(key=lambda row: row.get("time_text") or "", reverse=True)
    return hits[:limit]


def search(
    query: str,
    source_id: str = "",
    session_id: str = "",
    limit: int = 50,
    local_platform=None,
) -> List[dict]:
    tokens = tokenize(query)
    if not tokens:
        return []
    source_id = str(source_id or "").strip()
    session_id = str(session_id or "").strip()
    limit = max(1, min(int(limit or 50), 200))
    if source_id == "local":
        if local_platform is None:
            return []
        return search_local(local_platform, tokens, session_id, limit)
    if source_id:
        return search_synced(source_id, tokens, session_id, limit)

    hits = []
    if local_platform is not None:
        hits.extend(search_local(local_platform, tokens, session_id, min(limit, 80)))
    for src in synced_store.list_sources():
        hits.extend(search_synced(src["id"], tokens, session_id, min(limit, 80)))
    hits.sort(key=lambda row: row.get("time_text") or "", reverse=True)
    return hits[:limit]
