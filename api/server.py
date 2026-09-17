"""FastAPI server for chat analysis."""
import os
import socket
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timedelta
from urllib.parse import unquote, urlparse
import urllib.request
from typing import Optional, List
from collections import Counter

from fastapi import Depends, FastAPI, Query, HTTPException, Header, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# Add project root to path
_api_dir = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(_api_dir)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

# Import platform implementations (hyphenated names need importlib)
import importlib
_wechat_mod = importlib.import_module('core-wechat.chat_platform')
_wecom_mod = importlib.import_module('core-wecom.chat_platform')
_dingtalk_mod = importlib.import_module('core-dingtalk.chat_platform')
from shared import agent_update, api_keys, file_jobs, lan, message_search, synced_store
from shared.presence import PresenceHub
from shared.wecom_ssh import load_live_manifest, strip_jsonc
import json

WeChatPlatform = _wechat_mod.WeChatPlatform
WeComPlatform = _wecom_mod.WeComPlatform
DingTalkPlatform = _dingtalk_mod.DingTalkPlatform

PLATFORMS = {
    "wechat": WeChatPlatform,
    "wecom": WeComPlatform,
    "dingtalk": DingTalkPlatform,
}

def get_platform(name, **kwargs):
    cls = PLATFORMS.get(name)
    if not cls:
        raise ValueError(f"Unknown platform: {name}")
    return cls(**kwargs)

app = FastAPI(title="Chat Analysis API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SessionResponse(BaseModel):
    username: str
    display_name: str
    session_type: int = 0
    summary: str = ""
    last_time: str = ""
    unread: int = 0
    msg_count: int = 0
    synced_at: str = ""


class MessageResponse(BaseModel):
    time_text: str = ""
    sender: str = ""
    sender_id: str = ""
    text: str = ""
    msg_type: int = 0
    msg_type_label: str = ""
    hour: Optional[int] = None
    message_id: int = 0
    has_attachment: bool = False
    attachment_name: str = ""
    media_url: str = ""


def _message_response(m) -> MessageResponse:
    if isinstance(m, dict):
        return MessageResponse(
            time_text=m.get("time_text") or "",
            sender=m.get("sender") or "",
            sender_id=m.get("sender_id") or "",
            text=m.get("text") or "",
            msg_type=int(m.get("msg_type") or 0),
            msg_type_label=m.get("msg_type_label") or "",
            hour=m.get("hour"),
            message_id=int(m.get("message_id") or 0),
            has_attachment=bool(m.get("has_attachment") or m.get("media_url")),
            attachment_name=m.get("attachment_name") or "",
            media_url=m.get("media_url") or "",
        )
    return MessageResponse(
        time_text=m.time_text,
        sender=m.sender,
        sender_id=m.sender_id,
        text=m.text,
        msg_type=m.msg_type,
        msg_type_label=m.msg_type_label,
        hour=m.hour,
        message_id=m.message_id,
        has_attachment=m.has_attachment or bool(getattr(m, "media_url", "")),
        attachment_name=m.attachment_name,
        media_url=getattr(m, "media_url", "") or "",
    )


class ContactResponse(BaseModel):
    user_id: str
    nickname: str
    remark: str


class StatsResponse(BaseModel):
    total_messages: int = 0
    unique_senders: int = 0
    sender_stats: dict = {}
    hourly_distribution: dict = {}
    msg_type_distribution: dict = {}
    time_range: dict = {}
    top_senders: list = []
    activity_timeline: list = []


class PlatformInfo(BaseModel):
    name: str
    display_name: str
    detected: bool = False
    data_dir: str = ""


class SourceInfo(BaseModel):
    id: str
    kind: str = "remote"
    computer_name: str
    operator_name: str = ""
    username: str = ""
    account_id: str = ""
    host: str = ""
    last_sync: str = ""
    session_count: int = 0
    platform: str = "wecom"


class AgentUpdateInfo(BaseModel):
    version: str
    sha256: str
    size: int
    url: str = "/api/ingest/agent-exe"
    notes: str = ""
    changelog: list = []


class SearchHit(BaseModel):
    source_id: str
    source_name: str = ""
    session_id: str
    session_name: str = ""
    time_text: str = ""
    sender: str = ""
    sender_id: str = ""
    text: str = ""
    snippet: str = ""
    message_id: int = 0
    msg_type: int = 0
    attachment_name: str = ""
    media_url: str = ""


class ReadApiKeyInfo(BaseModel):
    name: str = "default"
    key: str = ""


class ReadApiInfo(BaseModel):
    enabled: bool = True
    key: str = ""
    keys: List[ReadApiKeyInfo] = []
    urls: List[str] = []
    example: str = ""


class IngestInfo(BaseModel):
    token: str
    port: int = 8767
    urls: List[str] = []
    web_port: int = 5173
    web_urls: List[str] = []
    read_api: Optional[ReadApiInfo] = None
    agent_update: Optional[AgentUpdateInfo] = None


_platforms_cache = {}
_INGEST_TOKEN_FILE = os.path.join(PROJECT_DIR, "export", "ingest_token.txt")


def _load_ingest_token() -> str:
    cfg_path = os.path.join(PROJECT_DIR, "config.jsonc")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            cfg = json.loads(strip_jsonc(f.read()))
        token = ((cfg.get("wecom_remote") or {}).get("ingest_token") or "").strip()
        if token:
            return token
    env = os.environ.get("WECOM_INGEST_TOKEN", "").strip()
    if env:
        return env
    if os.path.exists(_INGEST_TOKEN_FILE):
        return open(_INGEST_TOKEN_FILE, encoding="utf-8").read().strip()
    os.makedirs(os.path.dirname(_INGEST_TOKEN_FILE), exist_ok=True)
    token = uuid.uuid4().hex
    with open(_INGEST_TOKEN_FILE, "w", encoding="utf-8") as f:
        f.write(token)
    return token


def _lan_urls(port: int = 8767) -> List[str]:
    return lan.lan_urls(port)


def _check_ingest_token(payload_token: str = "", header_token: str = ""):
    expected = _load_ingest_token()
    got = (header_token or payload_token or "").strip()
    if not expected or got != expected:
        raise HTTPException(status_code=401, detail="Invalid ingest token")


def require_read_api_key(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    authorization: Optional[str] = Header(None),
    key: str = Query("", alias="key"),
) -> dict:
    if not api_keys.is_enabled():
        raise HTTPException(status_code=403, detail="Open API is disabled")
    token = api_keys.extract_token(x_api_key or "", authorization or "", key)
    found = api_keys.verify(token)
    if not found:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return found


def _v1_ok(data, **meta):
    payload = {"ok": True, "data": jsonable_encoder(data)}
    payload.update(meta)
    return payload


def _message_day(item) -> str:
    if isinstance(item, dict):
        text = item.get("time_text") or ""
    else:
        text = getattr(item, "time_text", "") or ""
    return str(text)[:10]


def _filter_v1_messages(rows, start_date: Optional[str], end_date: Optional[str],
                        offset: int, limit: int):
    filtered = []
    for item in rows:
        day = _message_day(item)
        if start_date and day and day < start_date:
            continue
        if end_date and day and day > end_date:
            continue
        filtered.append(item)
    sliced = filtered[offset:offset + limit]
    return sliced, len(filtered)


def _show_windows_balloon(title: str, message: str) -> None:
    if os.name != "nt":
        return
    safe_title = "".join(ch for ch in (title or "ChatInsight") if ch not in "'\"`")[:40]
    safe_msg = "".join(ch for ch in (message or "") if ch not in "'\"`")[:120]
    script = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n = New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon = [System.Drawing.SystemIcons]::Information;"
        "$n.Visible = $true;"
        f"$n.ShowBalloonTip(6000, '{safe_title}', '{safe_msg}', "
        "[System.Windows.Forms.ToolTipIcon]::Info);"
        "Start-Sleep -Seconds 7;"
        "$n.Dispose();"
    )
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        pass


def _desktop_alert(alert: dict) -> None:
    if (alert or {}).get("kind") == "offline":
        return
    threading.Thread(
        target=_show_windows_balloon,
        args=(alert.get("title") or "ChatInsight", alert.get("message") or ""),
        daemon=True,
    ).start()


presence = PresenceHub(on_alert=_desktop_alert)


def _client_source_id(payload: dict) -> str:
    computer_name = (payload.get("computer_name") or socket.gethostname()).strip()
    account_id = str(payload.get("account_id") or "")
    source_id = payload.get("source_id") or synced_store.source_id_for(computer_name, account_id)
    return synced_store._safe_id(source_id)


def _local_source() -> Optional[dict]:
    try:
        plat = WeComPlatform()
        data_dir = plat.detect_data_dir()
        if not data_dir:
            return None
        live = load_live_manifest()
        sessions = []
        encrypted = False
        try:
            from importlib import import_module
            wecom = import_module("core-wecom.chat_platform")
            encrypted = wecom._looks_like_encrypted_dir(data_dir)
        except Exception:
            encrypted = False
        if not encrypted:
            sessions = plat.list_sessions(limit=500)
        computer = socket.gethostname()
        kind = "local"
        host = ""
        if live and os.path.normcase(data_dir) == os.path.normcase(live.get("decrypted_dir") or ""):
            kind = "ssh"
            host = live.get("host") or ""
            computer = f"{host or computer}（SSH）"
        else:
            computer = f"{computer}（本机）"
        return {
            "id": "local",
            "kind": kind,
            "computer_name": computer,
            "operator_name": "",
            "username": "",
            "account_id": "",
            "host": host,
            "last_sync": "直连",
            "session_count": len(sessions),
            "platform": "wecom",
        }
    except Exception:
        return None


def _get_platform(name: str):
    if name not in _platforms_cache:
        try:
            plat = get_platform(name)
            data_dir = plat.detect_data_dir()
            if data_dir:
                plat.data_dir = data_dir
            _platforms_cache[name] = plat
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))
    return _platforms_cache[name]


@app.get("/api/platforms")
async def list_platforms():
    result = []
    for name, cls in PLATFORMS.items():
        try:
            plat = get_platform(name)
            data_dir = plat.detect_data_dir()
            result.append(PlatformInfo(
                name=name,
                display_name=cls.display_name,
                detected=data_dir is not None,
                data_dir=data_dir or "",
            ))
        except Exception:
            result.append(PlatformInfo(name=name, display_name=cls.display_name))
    return result


def _agent_update_payload() -> Optional[dict]:
    return agent_update.build_manifest(PROJECT_DIR)


@app.get("/api/ingest/info")
async def ingest_info():
    update = _agent_update_payload()
    api_urls = _lan_urls(8767)
    read_api = ReadApiInfo(**api_keys.homepage_info(api_urls))
    return IngestInfo(
        token=_load_ingest_token(),
        port=8767,
        urls=api_urls,
        web_port=5173,
        web_urls=_lan_urls(5173),
        read_api=read_api,
        agent_update=AgentUpdateInfo(**update) if update else None,
    )


@app.get("/api/sources")
async def list_sources():
    items = []
    local = _local_source()
    if local:
        items.append(SourceInfo(**local))
    for src in synced_store.list_sources():
        items.append(SourceInfo(**src))
    return items


@app.post("/api/ingest/wecom")
async def ingest_wecom(payload: dict, x_ingest_token: Optional[str] = Header(None)):
    _check_ingest_token(str(payload.get("token") or ""), x_ingest_token or "")
    try:
        result = synced_store.save_ingest(payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    names = [
        item.get("display_name") or item.get("id") or item.get("username") or ""
        for item in (payload.get("sessions") or [])
    ]
    presence.note_sync(
        result["source_id"],
        payload.get("operator_name") or result.get("operator_name") or "",
        result.get("computer_name") or "",
        names,
        result.get("saved_sessions") or 0,
        payload.get("host") or "",
    )
    return {"ok": True, **result}


@app.post("/api/ingest/heartbeat")
async def ingest_heartbeat(payload: dict, x_ingest_token: Optional[str] = Header(None)):
    _check_ingest_token(str(payload.get("token") or ""), x_ingest_token or "")
    source_id = _client_source_id(payload)
    result = presence.heartbeat(
        source_id,
        payload.get("operator_name") or "",
        payload.get("computer_name") or "",
        payload.get("host") or "",
    )
    result["source_id"] = source_id
    result["jobs"] = file_jobs.hub.pending_for(source_id)
    result["agent_update"] = _agent_update_payload()
    return result


@app.post("/api/ingest/file")
async def ingest_file(
    request: Request,
    x_ingest_token: Optional[str] = Header(None),
    x_job_id: Optional[str] = Header(None),
    x_filename: Optional[str] = Header(None),
):
    _check_ingest_token("", x_ingest_token or "")
    job_id = (x_job_id or "").strip()
    if not job_id:
        raise HTTPException(status_code=400, detail="X-Job-Id is required")
    try:
        length = int(request.headers.get("content-length") or 0)
    except ValueError:
        length = 0
    if length > file_jobs.MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail="file too large")
    data = await request.body()
    filename = unquote(x_filename or "")
    try:
        job = file_jobs.hub.save_bytes(job_id, filename, data)
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")
    except ValueError as exc:
        code = 413 if "large" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc))
    return {"ok": True, "job_id": job_id, "status": job["status"]}


@app.post("/api/ingest/file-result")
async def ingest_file_result(payload: dict, x_ingest_token: Optional[str] = Header(None)):
    _check_ingest_token(str(payload.get("token") or ""), x_ingest_token or "")
    job_id = str(payload.get("job_id") or "").strip()
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    status = str(payload.get("status") or "").strip()
    detail = str(payload.get("detail") or "")
    try:
        if status == "missing":
            job = file_jobs.hub.mark_missing(job_id, detail)
        elif status == "error":
            job = file_jobs.hub.mark_error(job_id, detail)
        else:
            raise HTTPException(status_code=400, detail="unsupported status")
    except KeyError:
        raise HTTPException(status_code=404, detail="job not found")
    return {"ok": True, "job_id": job_id, "status": job["status"]}


@app.post("/api/ingest/offline")
async def ingest_offline(payload: dict, x_ingest_token: Optional[str] = Header(None)):
    _check_ingest_token(str(payload.get("token") or ""), x_ingest_token or "")
    return presence.mark_offline(_client_source_id(payload))


@app.get("/api/ingest/agent-update")
async def ingest_agent_update():
    update = _agent_update_payload()
    if not update:
        raise HTTPException(status_code=404, detail="agent exe not published")
    return update


@app.get("/api/ingest/agent-exe")
def ingest_agent_exe(
    x_ingest_token: Optional[str] = Header(None),
    token: str = Query(""),
):
    _check_ingest_token(token, x_ingest_token or "")
    path = agent_update.agent_exe_path(PROJECT_DIR)
    if not path:
        raise HTTPException(status_code=404, detail="agent exe not published")
    return FileResponse(
        path,
        filename="WeComSyncAgent.exe",
        media_type="application/octet-stream",
    )


@app.get("/api/presence")
async def get_presence(since: int = Query(0, ge=0)):
    return presence.snapshot(since_id=since)


def _local_platform_or_none():
    try:
        plat = _get_platform("wecom")
        if plat.detect_data_dir():
            return plat
    except Exception:
        return None
    return None


@app.get("/api/search")
async def search_messages(
    q: str = Query(..., min_length=1, max_length=80),
    source_id: str = Query(""),
    session_id: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    local = None
    if source_id == "local":
        local = _local_platform_or_none()
    hits = message_search.search(
        q,
        source_id=source_id,
        session_id=session_id,
        limit=limit,
        local_platform=local,
    )
    return [SearchHit(**item) for item in hits]


@app.get("/api/sources/{source_id}/search")
async def search_source_messages(
    source_id: str,
    q: str = Query(..., min_length=1, max_length=80),
    session_id: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
):
    return await search_messages(q, source_id, session_id, limit)


@app.get("/api/sources/{source_id}/sessions")
async def list_source_sessions(source_id: str, limit: int = Query(200, ge=1, le=1000)):
    if source_id == "local":
        plat = _get_platform("wecom")
        sessions = plat.list_sessions(limit=limit)
        return [SessionResponse(
            username=s.username,
            display_name=s.display_name,
            session_type=s.session_type,
            summary=s.summary,
            last_time=s.last_time,
            unread=s.unread,
            msg_count=s.msg_count,
        ) for s in sessions]
    if not synced_store.get_source(source_id):
        raise HTTPException(status_code=404, detail="Unknown computer")
    sessions = synced_store.list_sessions(source_id)[:limit]
    return [SessionResponse(
        username=s.get("username") or "",
        display_name=s.get("display_name") or "",
        session_type=int(s.get("session_type") or 0),
        summary=s.get("summary") or "",
        last_time=s.get("last_time") or "",
        msg_count=int(s.get("msg_count") or 0),
        synced_at=s.get("synced_at") or "",
    ) for s in sessions]


@app.get("/api/sources/{source_id}/messages/{session_id}")
async def get_source_messages(
    source_id: str,
    session_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
):
    if source_id == "local":
        plat = _get_platform("wecom")
        start_time = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        end_time = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1) if end_date else None
        messages = plat.query_messages(session_id, start_time=start_time, end_time=end_time, limit=limit)
        return [_message_response(m) for m in messages]
    if not synced_store.get_source(source_id):
        raise HTTPException(status_code=404, detail="Unknown computer")
    rows = synced_store.list_messages(source_id, session_id, limit=limit)
    return [_message_response(m) for m in rows]


@app.get("/v1/health")
async def v1_health():
    return {"ok": True, "service": "chatinsight", "read_api": api_keys.is_enabled()}


@app.get("/v1/info")
async def v1_info(auth: dict = Depends(require_read_api_key)):
    return _v1_ok({
        "key_name": auth.get("name") or "key",
        "endpoints": [
            "GET /v1/health",
            "GET /v1/info",
            "GET /v1/sources",
            "GET /v1/sources/{source_id}/sessions",
            "GET /v1/sources/{source_id}/messages/{session_id}",
            "GET /v1/search?q=",
        ],
    })


@app.get("/v1/sources")
async def v1_sources(_auth: dict = Depends(require_read_api_key)):
    items = await list_sources()
    return _v1_ok(items, count=len(items))


@app.get("/v1/sources/{source_id}/sessions")
async def v1_source_sessions(
    source_id: str,
    limit: int = Query(200, ge=1, le=1000),
    _auth: dict = Depends(require_read_api_key),
):
    items = await list_source_sessions(source_id, limit)
    return _v1_ok(items, count=len(items), source_id=source_id)


@app.get("/v1/sources/{source_id}/messages/{session_id}")
async def v1_source_messages(
    source_id: str,
    session_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    offset: int = Query(0, ge=0, le=100000),
    limit: int = Query(200, ge=1, le=1000),
    _auth: dict = Depends(require_read_api_key),
):
    fetch_limit = 5000 if (start_date or end_date or offset) else limit
    rows = await get_source_messages(source_id, session_id, start_date, end_date, fetch_limit)
    data, total = _filter_v1_messages(rows, start_date, end_date, offset, limit)
    return _v1_ok(
        data,
        count=len(data),
        total=total,
        offset=offset,
        limit=limit,
        source_id=source_id,
        session_id=session_id,
    )


@app.get("/v1/search")
async def v1_search(
    q: str = Query(..., min_length=1, max_length=80),
    source_id: str = Query(""),
    session_id: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
    _auth: dict = Depends(require_read_api_key),
):
    items = await search_messages(q, source_id, session_id, limit)
    return _v1_ok(items, count=len(items), q=q)


@app.get("/api/sources/{source_id}/stats/{session_id}")
async def get_source_stats(
    source_id: str,
    session_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    if source_id == "local":
        return await get_stats("wecom", session_id, start_date, end_date)
    messages = await get_source_messages(source_id, session_id, start_date, end_date, 5000)
    if not messages:
        return StatsResponse()
    sender_counter = Counter(m.sender for m in messages if m.sender)
    hour_counter = Counter(m.hour for m in messages if m.hour is not None)
    type_counter = Counter(m.msg_type for m in messages)
    date_counter = Counter()
    for m in messages:
        day = (m.time_text or "")[:10]
        if len(day) == 10 and day[4] == "-":
            date_counter[day] += 1
    return StatsResponse(
        total_messages=len(messages),
        unique_senders=len(sender_counter),
        sender_stats=dict(sender_counter),
        hourly_distribution={str(h): c for h, c in sorted(hour_counter.items())},
        msg_type_distribution={str(t): c for t, c in type_counter.items()},
        time_range={},
        top_senders=[{"name": name, "count": count} for name, count in sender_counter.most_common(20)],
        activity_timeline=[{"date": d, "count": c} for d, c in sorted(date_counter.items())],
    )


@app.get("/api/{platform}/sessions")
async def list_sessions(platform: str, limit: int = Query(100, ge=1, le=1000)):
    plat = _get_platform(platform)
    sessions = plat.list_sessions(limit=limit)
    return [SessionResponse(
        username=s.username,
        display_name=s.display_name,
        session_type=s.session_type,
        summary=s.summary,
        last_time=s.last_time,
        unread=s.unread,
        msg_count=s.msg_count,
    ) for s in sessions]


@app.get("/api/{platform}/messages/{session_id}")
async def get_messages(
    platform: str,
    session_id: str,
    start_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="YYYY-MM-DD"),
    limit: int = Query(500, ge=1, le=5000),
):
    plat = _get_platform(platform)
    start_time = None
    end_time = None
    if start_date:
        start_time = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        end_time = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    messages = plat.query_messages(session_id, start_time=start_time,
                                   end_time=end_time, limit=limit)
    return [_message_response(m) for m in messages]


@app.get("/api/{platform}/contacts")
async def get_contacts(platform: str):
    plat = _get_platform(platform)
    contacts = plat.get_contacts()
    return [ContactResponse(
        user_id=c.user_id,
        nickname=c.nickname,
        remark=c.remark,
    ) for c in contacts]


@app.get("/api/{platform}/stats/{session_id}")
async def get_stats(
    platform: str,
    session_id: str,
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
):
    plat = _get_platform(platform)
    start_time = None
    end_time = None
    if start_date:
        start_time = datetime.strptime(start_date, "%Y-%m-%d")
    if end_date:
        end_time = datetime.strptime(end_date, "%Y-%m-%d") + timedelta(days=1)

    messages = plat.query_messages(session_id, start_time=start_time,
                                   end_time=end_time, limit=5000)

    if not messages:
        return StatsResponse()

    sender_counter = Counter(m.sender for m in messages if m.sender)
    hour_counter = Counter(m.hour for m in messages if m.hour is not None)
    type_counter = Counter(m.msg_type for m in messages)

    top_senders = sender_counter.most_common(20)

    time_range = {}
    if messages:
        times = [m.time for m in messages if m.time]
        if times:
            time_range = {
                "start": min(times).isoformat(),
                "end": max(times).isoformat(),
            }

    activity_timeline = []
    date_counter = Counter()
    for m in messages:
        if m.time:
            date_key = m.time.strftime("%Y-%m-%d")
            date_counter[date_key] += 1
    for date_key in sorted(date_counter.keys()):
        activity_timeline.append({"date": date_key, "count": date_counter[date_key]})

    return StatsResponse(
        total_messages=len(messages),
        unique_senders=len(sender_counter),
        sender_stats=dict(sender_counter),
        hourly_distribution={str(h): c for h, c in sorted(hour_counter.items())},
        msg_type_distribution={str(t): c for t, c in type_counter.items()},
        time_range=time_range,
        top_senders=[{"name": name, "count": count} for name, count in top_senders],
        activity_timeline=activity_timeline,
    )


@app.get("/api/{platform}/groups")
async def list_groups(platform: str):
    plat = _get_platform(platform)
    sessions = plat.list_sessions(limit=500)
    groups = [s for s in sessions if "@chatroom" in s.username or s.session_type == 2]
    return [SessionResponse(
        username=s.username,
        display_name=s.display_name,
        session_type=s.session_type,
        msg_count=s.msg_count,
    ) for s in groups]


_MEDIA_HOST_SUFFIXES = (
    ".qpic.cn",
    "qpic.cn",
    ".qlogo.cn",
    "qlogo.cn",
    ".weixin.qq.com",
    "weixin.qq.com",
)
_MEDIA_MAX_BYTES = 12 * 1024 * 1024


def _allowed_media_host(host: str) -> bool:
    host = (host or "").lower().rstrip(".")
    return any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _MEDIA_HOST_SUFFIXES)


def _file_response(path: str, filename: str = ""):
    return FileResponse(
        path,
        filename=filename or os.path.basename(path),
        content_disposition_type="attachment",
    )


@app.get("/api/sources/{source_id}/attachments/{message_id}")
def download_source_attachment(
    source_id: str,
    message_id: int,
    session_id: str = Query(""),
):
    filename = ""
    plat = _get_platform("wecom")
    getter = getattr(plat, "get_attachment_file", None)
    if not getter:
        raise HTTPException(status_code=404, detail="This platform does not support attachments")
    if source_id != "local":
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        item = synced_store.get_message(source_id, session_id, message_id)
        if not item:
            raise HTTPException(status_code=404, detail="Message not found")
        filename = item.get("attachment_name") or ""
        cached = file_jobs.stored_path(source_id, message_id, filename)
        if cached:
            return _file_response(cached, filename)
    try:
        path = getter(int(message_id), filename_hint=filename)
    except TypeError:
        path = getter(int(message_id))
    if path and os.path.isfile(path):
        return _file_response(path, filename)
    if source_id == "local":
        raise HTTPException(status_code=404, detail="文件不在本机缓存，查看聊天时不会自动下载")
    try:
        job = file_jobs.hub.request(source_id, message_id, session_id, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if job.get("status") == "ready" and job.get("path") and os.path.isfile(job["path"]):
        return _file_response(job["path"], filename or job.get("filename") or "")
    if job.get("status") == "missing":
        raise HTTPException(status_code=404, detail=job.get("detail") or "对方电脑未缓存该文件")
    if job.get("status") == "error":
        raise HTTPException(status_code=409, detail=job.get("detail") or "拉取失败")
    return JSONResponse(
        status_code=202,
        content={
            "status": job.get("status") or "pending",
            "job_id": job.get("job_id") or "",
            "detail": "正在等待远端助手回传文件",
        },
    )


@app.get("/api/media/proxy")
def proxy_media(url: str = Query(..., min_length=8, max_length=2000)):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not _allowed_media_host(parsed.hostname or ""):
        raise HTTPException(status_code=400, detail="Unsupported image host")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            content_type = (resp.headers.get("Content-Type") or "image/jpeg").split(";")[0].strip()
            if not content_type.startswith("image/"):
                raise HTTPException(status_code=415, detail="Remote content is not an image")
            data = resp.read(_MEDIA_MAX_BYTES + 1)
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to fetch image")
    if len(data) > _MEDIA_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large")
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/{platform}/attachments/{message_id}")
async def get_attachment(platform: str, message_id: int):
    plat = _get_platform(platform)
    getter = getattr(plat, "get_attachment_file", None)
    if not getter:
        raise HTTPException(status_code=404, detail="This platform does not support attachments")
    path = getter(int(message_id))
    if not path or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Attachment not found on this PC or remote Cache")
    return FileResponse(path, filename=os.path.basename(path))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8765)
