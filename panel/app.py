from __future__ import annotations

import os
import re
import subprocess
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import jwt
import qrcode
from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import database as db
from mtproxy_service import (
    build_client_secret,
    build_proxy_link,
    count_connections,
    get_public_ip,
    is_proxy_running,
    parse_stats_from_log,
    restart_proxy,
    start_proxy,
    stop_proxy,
    validate_domain,
)
from panel_service import apply_panel_port, is_port_available
from system_monitor import get_system_status

JWT_SECRET = os.getenv("MTP_PANEL_JWT_SECRET", "mtproxy-panel-secret-change-me")
JWT_ALGO = "HS256"
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="MTProxy Panel", version="2.0.0")
security = HTTPBearer(auto_error=False)

_stats_thread: Optional[threading.Thread] = None
_stats_stop = threading.Event()
_proxy_needs_restart = False


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    remark: str = ""
    traffic_limit_gb: float = Field(default=0, ge=0)
    expires_days: Optional[int] = Field(default=None, ge=1)


class UserUpdateRequest(BaseModel):
    remark: Optional[str] = None
    enabled: Optional[bool] = None
    traffic_limit_gb: Optional[float] = Field(default=None, ge=0)
    expires_days: Optional[int] = Field(default=None, ge=0)
    reset_traffic: Optional[bool] = None


class SettingsUpdateRequest(BaseModel):
    panel_port: Optional[int] = Field(default=None, ge=1024, le=65535)
    proxy_port: Optional[int] = Field(default=None, ge=1, le=65535)
    domain: Optional[str] = None
    fake_tls_mode: Optional[str] = None
    adtag: Optional[str] = None
    public_ip: Optional[str] = None
    skip_domain_check: Optional[bool] = False


class AdminUpdateRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=6, max_length=64)


def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def verify_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        return jwt.decode(creds.credentials, JWT_SECRET, algorithms=[JWT_ALGO])["sub"]
    except jwt.PyJWTError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已过期")


def format_bytes(num: int) -> str:
    if num < 1024:
        return f"{num} B"
    if num < 1024 ** 2:
        return f"{num / 1024:.2f} KB"
    if num < 1024 ** 3:
        return f"{num / 1024 ** 2:.2f} MB"
    return f"{num / 1024 ** 3:.2f} GB"


def get_online_user_ids() -> set:
    stats = parse_stats_from_log()
    online: set = set()
    user_map = {f"user{u['id']}": u["id"] for u in db.list_users()}
    for key, s in stats.items():
        uid = user_map.get(key)
        if uid and s.get("connects", 0) > 0:
            online.add(uid)
    return online


def user_to_response(
    user: Dict[str, Any], settings: Dict[str, str], online_ids: Optional[set] = None
) -> Dict[str, Any]:
    server = settings.get("public_ip") or get_public_ip()
    port = int(settings.get("proxy_port", 443))
    mode = settings.get("fake_tls_mode", "ee")
    domain = settings.get("domain", "azure.microsoft.com")
    client_secret = build_client_secret(user["secret"], domain, mode)
    tg_link, http_link = build_proxy_link(server, port, client_secret)

    total = user["upload_bytes"] + user["download_bytes"]
    limit_gb = user["traffic_limit_gb"] or 0
    limit_bytes = int(limit_gb * 1024 ** 3) if limit_gb > 0 else 0

    expired = False
    if user.get("expires_at"):
        try:
            exp = datetime.fromisoformat(user["expires_at"])
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            expired = datetime.now(timezone.utc) >= exp
        except ValueError:
            pass

    over_quota = limit_bytes > 0 and total >= limit_bytes
    traffic_percent = round(total / limit_bytes * 100, 1) if limit_bytes > 0 else 0
    is_active = bool(user["enabled"]) and not expired and not over_quota
    is_online = bool(online_ids and user["id"] in online_ids and is_active)

    return {
        "id": user["id"],
        "remark": user["remark"],
        "secret": user["secret"],
        "client_secret": client_secret,
        "enabled": is_active,
        "is_online": is_online,
        "raw_enabled": bool(user["enabled"]),
        "traffic_limit_gb": limit_gb,
        "traffic_percent": min(traffic_percent, 100),
        "upload_bytes": user["upload_bytes"],
        "download_bytes": user["download_bytes"],
        "total_bytes": total,
        "upload_human": format_bytes(user["upload_bytes"]),
        "download_human": format_bytes(user["download_bytes"]),
        "total_human": format_bytes(total),
        "expires_at": user.get("expires_at"),
        "expired": expired,
        "over_quota": over_quota,
        "created_at": user["created_at"],
        "tg_link": tg_link,
        "http_link": http_link,
    }


def _stats_collector_loop() -> None:
    global _proxy_needs_restart
    last_stats: Dict[str, Dict[str, int]] = {}
    while not _stats_stop.is_set():
        try:
            disabled = db.disable_expired_and_over_quota()
            if disabled > 0:
                _proxy_needs_restart = True

            current = parse_stats_from_log()
            user_map = {f"user{u['id']}": u["id"] for u in db.list_users()}

            for key, stats in current.items():
                user_id = user_map.get(key)
                if not user_id:
                    continue
                prev = last_stats.get(key, {"upload": 0, "download": 0})
                up_delta = max(0, stats.get("upload", 0) - prev.get("upload", 0))
                down_delta = max(0, stats.get("download", 0) - prev.get("download", 0))
                if up_delta or down_delta:
                    db.add_traffic(user_id, up_delta, down_delta)
            last_stats = current

            if _proxy_needs_restart:
                restart_proxy()
                _proxy_needs_restart = False
        except Exception:
            pass
        _stats_stop.wait(15)


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    global _stats_thread
    _stats_stop.clear()
    _stats_thread = threading.Thread(target=_stats_collector_loop, daemon=True)
    _stats_thread.start()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stats_stop.set()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/auth/login")
def login(body: LoginRequest) -> Dict[str, str]:
    if not db.verify_admin(body.username, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    return {"token": create_token(body.username), "username": body.username}


@app.get("/api/dashboard")
def dashboard(_: str = Depends(verify_token)) -> Dict[str, Any]:
    settings = db.get_all_settings()
    port = int(settings.get("proxy_port", 443))
    online_ids = get_online_user_ids()
    users = [user_to_response(u, settings, online_ids) for u in db.list_users()]

    return {
        "system": get_system_status(),
        "proxy": {
            "running": is_proxy_running(),
            "connections": count_connections(port),
            "port": port,
            "domain": settings.get("domain"),
            "fake_tls_mode": settings.get("fake_tls_mode", "ee"),
            "public_ip": settings.get("public_ip") or get_public_ip(),
        },
        "users": users,
        "stats": {
            "total_users": len(users),
            "active_users": sum(1 for u in users if u["enabled"]),
            "total_traffic": sum(u["total_bytes"] for u in users),
            "total_traffic_human": format_bytes(sum(u["total_bytes"] for u in users)),
        },
    }


@app.get("/api/users")
def get_users(_: str = Depends(verify_token)) -> List[Dict[str, Any]]:
    settings = db.get_all_settings()
    online_ids = get_online_user_ids()
    return [user_to_response(u, settings, online_ids) for u in db.list_users()]


@app.post("/api/users")
def add_user(body: UserCreateRequest, _: str = Depends(verify_token)) -> Dict[str, Any]:
    user = db.create_user(body.remark, body.traffic_limit_gb, body.expires_days)
    restart_proxy()
    return user_to_response(user, db.get_all_settings(), get_online_user_ids())


@app.put("/api/users/{user_id}")
def edit_user(
    user_id: int, body: UserUpdateRequest, _: str = Depends(verify_token)
) -> Dict[str, Any]:
    fields: Dict[str, Any] = {}
    if body.remark is not None:
        fields["remark"] = body.remark
    if body.enabled is not None:
        fields["enabled"] = 1 if body.enabled else 0
    if body.traffic_limit_gb is not None:
        fields["traffic_limit_gb"] = body.traffic_limit_gb
    if body.expires_days is not None:
        if body.expires_days == 0:
            fields["expires_at"] = None
        else:
            exp = datetime.now(timezone.utc) + timedelta(days=body.expires_days)
            fields["expires_at"] = exp.isoformat()
    if body.reset_traffic:
        fields["upload_bytes"] = 0
        fields["download_bytes"] = 0

    user = db.update_user(user_id, **fields)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    restart_proxy()
    return user_to_response(user, db.get_all_settings(), get_online_user_ids())


@app.delete("/api/users/{user_id}")
def remove_user(user_id: int, _: str = Depends(verify_token)) -> Dict[str, str]:
    if not db.delete_user(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    restart_proxy()
    return {"status": "ok"}


@app.get("/api/users/{user_id}/qrcode")
def user_qrcode(user_id: int, _: str = Depends(verify_token)) -> Response:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    info = user_to_response(user, db.get_all_settings(), get_online_user_ids())
    from io import BytesIO

    buf = BytesIO()
    qrcode.make(info["tg_link"]).save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/api/settings")
def get_settings(_: str = Depends(verify_token)) -> Dict[str, Any]:
    settings = db.get_all_settings()
    return {
        "panel_port": int(settings.get("panel_port", 8088)),
        "proxy_port": int(settings.get("proxy_port", 443)),
        "domain": settings.get("domain", ""),
        "fake_tls_mode": settings.get("fake_tls_mode", "ee"),
        "adtag": settings.get("adtag", ""),
        "public_ip": settings.get("public_ip", ""),
        "admin_user": settings.get("admin_user", "admin"),
    }


@app.put("/api/settings")
def update_settings(
    body: SettingsUpdateRequest, _: str = Depends(verify_token)
) -> Dict[str, str]:
    messages = []
    old_panel_port = int(db.get_setting("panel_port", "8088"))

    if body.panel_port is not None:
        if body.panel_port != old_panel_port and not is_port_available(body.panel_port):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"面板端口 {body.panel_port} 已被占用")
        db.set_setting("panel_port", str(body.panel_port))

    if body.proxy_port is not None:
        if not is_port_available(body.proxy_port) and body.proxy_port != int(db.get_setting("proxy_port", "443")):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"代理端口 {body.proxy_port} 已被占用")
        db.set_setting("proxy_port", str(body.proxy_port))

    if body.domain is not None:
        if not re.match(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$", body.domain):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "域名格式不正确")
        if not body.skip_domain_check and not validate_domain(body.domain):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "域名无法访问，请更换或勾选跳过检测")
        db.set_setting("domain", body.domain)

    if body.fake_tls_mode is not None:
        if body.fake_tls_mode not in ("ee", "dd", "off"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "混淆模式支持 ee / dd / off")
        db.set_setting("fake_tls_mode", body.fake_tls_mode)

    if body.adtag is not None:
        if body.adtag and not re.match(r"^[A-Za-z0-9]{32}$", body.adtag):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "TAG 须为 32 位字母数字")
        db.set_setting("adtag", body.adtag)

    if body.public_ip is not None:
        db.set_setting("public_ip", body.public_ip)

    restart_proxy()
    messages.append("代理已重启")

    new_panel_port = int(db.get_setting("panel_port", "8088"))
    if body.panel_port is not None and new_panel_port != old_panel_port:
        if apply_panel_port(new_panel_port):
            messages.append(f"面板端口已切换为 {new_panel_port}，服务已重启")
        else:
            messages.append("面板端口已保存，请手动执行: systemctl restart mtproxy-panel")

    return {"status": "ok", "message": "；".join(messages)}


@app.put("/api/settings/admin")
def update_admin(body: AdminUpdateRequest, _: str = Depends(verify_token)) -> Dict[str, str]:
    db.update_admin(body.username, body.password)
    return {"status": "ok"}


@app.post("/api/proxy/restart")
def proxy_restart(_: str = Depends(verify_token)) -> Dict[str, Any]:
    return {"running": restart_proxy()}


@app.post("/api/proxy/start")
def proxy_start(_: str = Depends(verify_token)) -> Dict[str, Any]:
    return {"running": start_proxy()}


@app.post("/api/proxy/stop")
def proxy_stop(_: str = Depends(verify_token)) -> Dict[str, Any]:
    stop_proxy()
    return {"running": False}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")