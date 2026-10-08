from __future__ import annotations

import os
import re
import secrets
import subprocess
import sys
import threading
import time
import logging
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import jwt
import qrcode
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, status
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

JWT_ALGO = "HS256"
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

logger = logging.getLogger("mtproxy-panel")

app = FastAPI(title="MTProxy Panel", version="2.0.0")
security = HTTPBearer(auto_error=False)

_stats_thread: Optional[threading.Thread] = None
_stats_stop = threading.Event()
_proxy_needs_restart = False

# SOCKS5 进程管理
_socks5_proc: Optional[subprocess.Popen] = None
_socks5_lock = threading.Lock()


def _socks5_env() -> Dict[str, str]:
    env = os.environ.copy()
    env["SOCKS5_PORT"] = db.get_setting("socks5_port", "1080")
    # 让子进程找到 panel 目录（database.py）
    panel_dir = str(Path(__file__).parent)
    env["PYTHONPATH"] = panel_dir + os.pathsep + env.get("PYTHONPATH", "")
    return env


def is_socks5_running() -> bool:
    with _socks5_lock:
        return _socks5_proc is not None and _socks5_proc.poll() is None


def start_socks5() -> bool:
    with _socks5_lock:
        global _socks5_proc
        if _socks5_proc is not None and _socks5_proc.poll() is None:
            return True
        panel_dir = Path(__file__).parent
        _socks5_proc = subprocess.Popen(
            [sys.executable, str(panel_dir / "socks5_service.py")],
            env=_socks5_env(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True


def stop_socks5() -> None:
    with _socks5_lock:
        global _socks5_proc
        if _socks5_proc is not None:
            try:
                _socks5_proc.terminate()
                _socks5_proc.wait(timeout=5)
            except Exception:
                try:
                    _socks5_proc.kill()
                except Exception:
                    pass
            _socks5_proc = None

_jwt_secret: Optional[str] = None


def get_jwt_secret() -> str:
    """JWT 密钥：环境变量 > 数据库持久化 > 首次生成随机值。

    原来没配环境变量就用硬编码默认值，谁都知道，能直接伪造 token。
    """
    global _jwt_secret
    if _jwt_secret:
        return _jwt_secret
    env = os.getenv("MTP_PANEL_JWT_SECRET") or os.getenv("MTP_JWT_SECRET")
    if env:
        _jwt_secret = env
        return env
    stored = db.get_setting("jwt_secret", "")
    if not stored:
        stored = secrets.token_hex(32)
        db.set_setting("jwt_secret", stored)
    _jwt_secret = stored
    return stored


# 登录限流：单 IP 60 秒内最多 5 次失败
_login_hits: Dict[str, List[float]] = {}
_LOGIN_MAX = 5
_LOGIN_WINDOW = 60.0


def _login_allowed(ip: str) -> bool:
    now = time.monotonic()
    hits = [t for t in _login_hits.get(ip, []) if now - t < _LOGIN_WINDOW]
    _login_hits[ip] = hits
    return len(hits) < _LOGIN_MAX


def _login_record(ip: str, ok: bool) -> None:
    if ok:
        _login_hits.pop(ip, None)
    else:
        _login_hits.setdefault(ip, []).append(time.monotonic())


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


class NodeCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=128)
    agent_port: int = Field(default=8899, ge=1, le=65535)
    api_token: str = Field(min_length=8, max_length=128)
    port_start: int = Field(default=10000, ge=1, le=65535)
    port_end: int = Field(default=20000, ge=1, le=65535)


class NodeRegisterRequest(BaseModel):
    install_token: str
    name: str = Field(min_length=1, max_length=64)
    host: str = Field(min_length=1, max_length=128)
    agent_port: int = Field(default=8899, ge=1, le=65535)
    api_token: str = Field(min_length=8, max_length=128)
    proxy_port: int = Field(default=443, ge=1, le=65535)
    public_ip: str = ""
    port_start: int = Field(default=10000, ge=1, le=65535)
    port_end: int = Field(default=20000, ge=1, le=65535)


class NodeUpdateRequest(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=64)
    proxy_port: Optional[int] = Field(default=None, ge=1, le=65535)
    domain: Optional[str] = None


def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc) + timedelta(days=7)}
    return jwt.encode(payload, get_jwt_secret(), algorithm=JWT_ALGO)


def verify_token(
    creds: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not creds or creds.scheme.lower() != "bearer":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录")
    try:
        return jwt.decode(creds.credentials, get_jwt_secret(), algorithms=[JWT_ALGO])["sub"]
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
        "last_seen": user.get("last_seen"),
        "tg_link": tg_link,
        "http_link": http_link,
        "socks_user": f"user{user['id']}",
        "socks_pass": user.get("socks_password") or "",
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
            logger.exception("stats collector 出错")
        _stats_stop.wait(15)


@app.on_event("startup")
def on_startup() -> None:
    db.init_db()
    global _stats_thread
    _stats_stop.clear()
    _stats_thread = threading.Thread(target=_stats_collector_loop, daemon=True)
    _stats_thread.start()
    # 节点状态轮询
    _node_thread = threading.Thread(target=_node_poller_loop, daemon=True)
    _node_thread.start()
    # SOCKS5 自启
    if db.get_setting("socks5_enabled", "0") == "1":
        start_socks5()


@app.on_event("shutdown")
def on_shutdown() -> None:
    _stats_stop.set()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.post("/api/auth/login")
def login(body: LoginRequest, request: Request) -> Dict[str, str]:
    ip = request.client.host if request.client else "unknown"
    if not _login_allowed(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "尝试次数过多，请稍后再试")
    if not db.verify_admin(body.username, body.password):
        _login_record(ip, False)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
    _login_record(ip, True)
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
def add_user(
    body: UserCreateRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_token),
) -> Dict[str, Any]:
    user = db.create_user(body.remark, body.traffic_limit_gb, body.expires_days)
    # 代理重启约 3 秒，放后台，不阻塞接口返回
    background_tasks.add_task(restart_proxy)
    background_tasks.add_task(_sync_all_nodes_async)
    return user_to_response(user, db.get_all_settings(), get_online_user_ids())


@app.put("/api/users/{user_id}")
def edit_user(
    user_id: int,
    body: UserUpdateRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_token),
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
    background_tasks.add_task(restart_proxy)
    background_tasks.add_task(_sync_all_nodes_async)
    return user_to_response(user, db.get_all_settings(), get_online_user_ids())


@app.delete("/api/users/{user_id}")
def remove_user(
    user_id: int, background_tasks: BackgroundTasks, _: str = Depends(verify_token)
) -> Dict[str, str]:
    if not db.delete_user(user_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    background_tasks.add_task(restart_proxy)
    background_tasks.add_task(_sync_all_nodes_async)
    return {"status": "ok"}


@app.get("/api/users/{user_id}/qrcode")
def user_qrcode(user_id: int, _: str = Depends(verify_token)) -> Response:
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    info = user_to_response(user, db.get_all_settings(), get_online_user_ids())

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
    body: SettingsUpdateRequest,
    background_tasks: BackgroundTasks,
    _: str = Depends(verify_token),
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
        if body.public_ip:
            import ipaddress
            try:
                ipaddress.IPv4Address(body.public_ip.strip())
            except ValueError:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "只支持 IPv4 地址")
        db.set_setting("public_ip", body.public_ip.strip() if body.public_ip else "")

    background_tasks.add_task(restart_proxy)
    messages.append("代理正在后台重启")

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


# ============ SOCKS5 代理 ============

@app.get("/api/socks5/status")
def socks5_status(_: str = Depends(verify_token)) -> Dict[str, Any]:
    return {
        "running": is_socks5_running(),
        "enabled": db.get_setting("socks5_enabled", "0") == "1",
        "port": int(db.get_setting("socks5_port", "1080")),
    }


@app.post("/api/socks5/start")
def socks5_start(_: str = Depends(verify_token)) -> Dict[str, Any]:
    db.set_setting("socks5_enabled", "1")
    return {"running": start_socks5()}


@app.post("/api/socks5/stop")
def socks5_stop(_: str = Depends(verify_token)) -> Dict[str, Any]:
    db.set_setting("socks5_enabled", "0")
    stop_socks5()
    return {"running": False}


@app.put("/api/socks5/port")
def socks5_set_port(body: Dict[str, int], _: str = Depends(verify_token)) -> Dict[str, Any]:
    port = body.get("port", 1080)
    if not 1 <= port <= 65535:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "端口范围 1-65535")
    db.set_setting("socks5_port", str(port))
    # 重启生效
    if is_socks5_running():
        stop_socks5()
        start_socks5()
    return {"status": "ok", "port": port}


# ============ 多服务器节点管理 ============

import json as _json
import urllib.request as _urlreq


def _node_api_call(node: Dict[str, Any], path: str, method: str = "GET",
                   data: Optional[Dict[str, Any]] = None,
                   timeout: int = 8) -> Optional[Dict[str, Any]]:
    """调用节点 agent 接口，失败返回 None。"""
    url = f"http://{node['host']}:{node['agent_port']}{path}"
    headers = {
        "Authorization": f"Bearer {node['api_token']}",
        "Content-Type": "application/json",
    }
    body = _json.dumps(data).encode() if data is not None else None
    req = _urlreq.Request(url, data=body, headers=headers, method=method)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            return _json.loads(resp.read().decode())
    except Exception as e:
        logger.warning(f"节点 {node['name']}({node['host']}) 调用失败 {path}: {e}")
        return None


def _sync_users_to_node(node: Dict[str, Any]) -> bool:
    """把用户列表推送到节点，返回是否成功。"""
    users = [
        {"secret": u["secret"], "enabled": bool(u["enabled"])}
        for u in db.list_users()
    ]
    result = _node_api_call(node, "/sync-users", "POST", {"users": users})
    return bool(result and result.get("status") == "ok")


def _node_poller_loop() -> None:
    """后台轮询节点状态（60 秒一次）。"""
    while not _stats_stop.is_set():
        try:
            for node in db.list_nodes():
                stats = _node_api_call(node, "/stats")
                if stats:
                    db.update_node_status(node["id"], "online", stats)
                else:
                    db.update_node_status(node["id"], "offline")
        except Exception:
            logger.exception("节点轮询出错")
        _stats_stop.wait(60)


def _sync_all_nodes_async() -> None:
    """用户变更后异步同步到所有在线节点。"""
    def _run():
        for node in db.list_nodes():
            if node["status"] == "online":
                _sync_users_to_node(node)
    threading.Thread(target=_run, daemon=True).start()


@app.get("/api/nodes")
def get_nodes(_: str = Depends(verify_token)) -> List[Dict[str, Any]]:
    nodes = db.list_nodes()
    # 隐藏 api_token，只返回掩码；附带域名
    for n in nodes:
        n["api_token"] = "***" if n.get("api_token") else ""
        n["domain"] = db.get_node_domain(n["id"])
    return nodes


@app.post("/api/nodes")
def add_node(body: NodeCreateRequest, _: str = Depends(verify_token)) -> Dict[str, Any]:
    if body.port_start >= body.port_end:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "端口范围起始必须小于结束")
    node = db.create_node(
        name=body.name, host=body.host, agent_port=body.agent_port,
        api_token=body.api_token,
        port_start=body.port_start, port_end=body.port_end,
    )
    # 立即尝试连接并同步用户
    stats = _node_api_call(node, "/stats")
    if stats:
        db.update_node_status(node["id"], "online", stats)
        _sync_users_to_node(node)
        node = db.get_node(node["id"])
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "无法连接到节点 agent，请检查 IP/端口/Token")
    node["api_token"] = "***"
    return node



# ============ 端口转发 ============
class ForwardRuleRequest(BaseModel):
    name: str = ""
    rule_type: str = "port"
    listen_node_id: int = 0
    listen_port: int = 0
    target_host: str = ""
    target_port: int = 0
    chain_id: int = 0
    chain_order: int = 0
    protocol: str = "tcp"
    user_id: int = 0
    speed_limit_mbps: int = 0
    traffic_limit_gb: float = 0

class ForwardChainRequest(BaseModel):
    name: str = ""

def _get_listen_node(rule: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """获取规则的监听节点。listen_node_id=0 表示本机。"""
    if rule["listen_node_id"] == 0:
        return None  # 本机特殊处理
    return db.get_node(rule["listen_node_id"])

def _forward_start_on_node(node: Optional[Dict[str, Any]], rule: Dict[str, Any]) -> bool:
    """在指定节点上启动转发。node=None 表示本机。"""
    data = {
        "rule_id": rule["id"],
        "listen_port": rule["listen_port"],
        "target_host": rule["target_host"],
        "target_port": rule["target_port"],
        "protocol": rule.get("protocol", "tcp"),
    }
    if node is None:
        # 本机：直接调本地转发管理
        try:
            from forward_service import forward_start as local_start
            return local_start(
                rule_id=data["rule_id"], listen_port=data["listen_port"],
                target_host=data["target_host"], target_port=data["target_port"],
                protocol=data.get("protocol", "tcp"))
        except Exception as e:
            logger.warning(f"本机转发启动失败: {e}")
            return False
    result = _node_api_call(node, "/forward/start", method="POST", data=data, timeout=15)
    return bool(result and result.get("ok"))

def _forward_stop_on_node(node: Optional[Dict[str, Any]], rule_id: int) -> bool:
    if node is None:
        try:
            from forward_service import forward_stop as local_stop
            local_stop(rule_id)
            return True
        except Exception:
            return False
    result = _node_api_call(node, "/forward/stop", method="POST",
                           data={"rule_id": rule_id}, timeout=10)
    return bool(result and result.get("ok"))

@app.get("/api/forward/rules")
def list_forward_rules(_: str = Depends(verify_token)) -> List[Dict[str, Any]]:
    rules = db.list_forward_rules()
    nodes = {n["id"]: n for n in db.list_nodes()}
    users = {u["id"]: u for u in db.list_users()}
    for r in rules:
        nid = r["listen_node_id"]
        r["listen_node_name"] = "本机" if nid == 0 else nodes.get(nid, {}).get("name", "未知")
        uid = r.get("user_id", 0)
        r["user_name"] = users.get(uid, {}).get("remark", "") if uid else ""
    return rules

@app.post("/api/forward/rules")
def create_forward_rule(body: ForwardRuleRequest, _: str = Depends(verify_token)) -> Dict[str, Any]:
    # 端口范围与冲突检查
    if body.listen_node_id != 0:
        node = db.get_node(body.listen_node_id)
        if not node:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "监听机器不存在")
        ps, pe = node.get("port_start", 10000), node.get("port_end", 20000)
        if not (ps <= body.listen_port <= pe):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"监听端口 {body.listen_port} 不在该机器分配范围 {ps}-{pe} 内")
        for r in db.list_forward_rules():
            if r["listen_node_id"] == body.listen_node_id and r["listen_port"] == body.listen_port:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"端口 {body.listen_port} 在该机器上已被隧道「{r['name']}」占用")

    if not body.listen_port or not body.target_host or not body.target_port:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "监听端口、目标地址、目标端口必填")
    if body.listen_node_id != 0 and not db.get_node(body.listen_node_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "监听节点不存在")
    rule = db.create_forward_rule(
        name=body.name or f"{body.listen_port}→{body.target_host}:{body.target_port}",
        rule_type=body.rule_type, listen_node_id=body.listen_node_id,
        listen_port=body.listen_port, target_host=body.target_host,
        target_port=body.target_port, chain_id=body.chain_id,
        chain_order=body.chain_order, protocol=body.protocol,
        user_id=body.user_id, speed_limit_mbps=body.speed_limit_mbps,
        traffic_limit_gb=body.traffic_limit_gb)
    # 自动启动
    node = _get_listen_node(rule)
    if _forward_start_on_node(node, rule):
        db.update_forward_rule(rule["id"], running=1)
        rule["running"] = 1
    return rule

@app.delete("/api/forward/rules/{rule_id}")
def delete_forward_rule(rule_id: int, _: str = Depends(verify_token)) -> Dict[str, str]:
    rule = db.get_forward_rule(rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    node = _get_listen_node(rule)
    _forward_stop_on_node(node, rule_id)
    db.delete_forward_rule(rule_id)
    return {"status": "ok"}

@app.post("/api/forward/rules/{rule_id}/start")
def start_forward_rule(rule_id: int, _: str = Depends(verify_token)) -> Dict[str, Any]:
    rule = db.get_forward_rule(rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    node = _get_listen_node(rule)
    if _forward_start_on_node(node, rule):
        db.update_forward_rule(rule_id, running=1)
        return {"status": "ok", "running": True}
    raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "转发启动失败")

@app.post("/api/forward/rules/{rule_id}/stop")
def stop_forward_rule(rule_id: int, _: str = Depends(verify_token)) -> Dict[str, Any]:
    rule = db.get_forward_rule(rule_id)
    if not rule:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    node = _get_listen_node(rule)
    _forward_stop_on_node(node, rule_id)
    db.update_forward_rule(rule_id, running=0)
    return {"status": "ok", "running": False}

@app.get("/api/forward/chains")
def list_forward_chains(_: str = Depends(verify_token)) -> List[Dict[str, Any]]:
    chains = db.list_forward_chains()
    rules = db.list_forward_rules()
    nodes = {n["id"]: n for n in db.list_nodes()}
    for c in chains:
        c["rules"] = sorted(
            [r for r in rules if r["chain_id"] == c["id"]],
            key=lambda x: x["chain_order"])
        for r in c["rules"]:
            nid = r["listen_node_id"]
            r["listen_node_name"] = "本机" if nid == 0 else nodes.get(nid, {}).get("name", "未知")
    return chains

@app.post("/api/forward/chains")
def create_forward_chain(body: ForwardChainRequest, _: str = Depends(verify_token)) -> Dict[str, Any]:
    if not body.name:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "链路名称必填")
    return db.create_forward_chain(body.name)

@app.delete("/api/forward/chains/{chain_id}")
def delete_forward_chain(chain_id: int, _: str = Depends(verify_token)) -> Dict[str, str]:
    rules = [r for r in db.list_forward_rules() if r["chain_id"] == chain_id]
    for r in rules:
        node = _get_listen_node(r)
        _forward_stop_on_node(node, r["id"])
    db.delete_forward_chain(chain_id)
    return {"status": "ok"}


@app.delete("/api/nodes/{node_id}")
def remove_node(node_id: int, _: str = Depends(verify_token)) -> Dict[str, str]:
    if not db.delete_node(node_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节点不存在")
    return {"status": "ok"}


@app.put("/api/nodes/{node_id}")
def update_node(node_id: int, body: NodeUpdateRequest, _: str = Depends(verify_token)) -> Dict[str, Any]:
    node = db.get_node(node_id)
    if not node:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节点不存在")
    fields = {k: v for k, v in body.dict().items() if v is not None}
    if not fields:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "没有要更新的字段")
    node = db.update_node(node_id, **fields)
    # 推送配置到节点 agent（端口/域名变更自动重启代理）
    cfg_push = {}
    if "proxy_port" in fields:
        cfg_push["proxy_port"] = fields["proxy_port"]
    if "domain" in fields:
        cfg_push["domain"] = fields["domain"]
    if cfg_push and node["status"] == "online":
        _node_api_call(node, "/config", "POST", cfg_push)
    node["api_token"] = "***"
    node["domain"] = db.get_node_domain(node_id)
    return node


@app.get("/api/nodes/install-command")
def get_install_command(request: Request, _: str = Depends(verify_token)) -> Dict[str, str]:
    """生成一键安装命令。"""
    token = db.get_install_token()
    # 面板公网地址：优先用配置的 public_ip，否则用请求 Host
    public_ip = db.get_setting("public_ip", "")
    panel_port = db.get_setting("panel_port", "8088")
    if public_ip:
        panel_url = f"http://{public_ip}:{panel_port}"
    else:
        host = request.headers.get("host", "").split(":")[0]
        panel_url = f"http://{host}:{panel_port}"
    cmd = (
        f"curl -fsSL https://raw.githubusercontent.com/"
        f"zxcvdyq888-create/mtproxy-panel/main/install-node.sh "
        f"| bash -s -- {panel_url} {token}"
    )
    return {"command": cmd, "panel_url": panel_url}


@app.post("/api/nodes/register")
def register_node(body: NodeRegisterRequest) -> Dict[str, Any]:
    """节点自助注册（安装脚本调用，用 install_token 鉴权）。"""
    if not db.verify_install_token(body.install_token):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "安装令牌无效或已过期")
    # 同一 host 已存在则更新
    for n in db.list_nodes():
        if n["host"] == body.host:
            return {"status": "ok", "node_id": n["id"], "message": "节点已存在"}
    node = db.create_node(
        name=body.name, host=body.host, agent_port=body.agent_port,
        api_token=body.api_token, proxy_port=body.proxy_port,
        public_ip=body.public_ip,
        port_start=body.port_start, port_end=body.port_end,
    )
    # 注册后立即同步用户
    _sync_users_to_node(node)
    return {"status": "ok", "node_id": node["id"]}


@app.post("/api/nodes/{node_id}/sync")
def sync_node(node_id: int, _: str = Depends(verify_token)) -> Dict[str, Any]:
    node = db.get_node(node_id)
    if not node:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节点不存在")
    ok = _sync_users_to_node(node)
    return {"status": "ok" if ok else "failed"}


@app.get("/api/nodes/{node_id}/link/{user_id}")
def get_node_user_link(node_id: int, user_id: int, _: str = Depends(verify_token)) -> Dict[str, str]:
    """生成指定节点上指定用户的 tg 链接。"""
    node = db.get_node(node_id)
    if not node:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "节点不存在")
    user = db.get_user(user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    settings = db.get_all_settings()
    ip = node["public_ip"] or node["host"]
    port = node["proxy_port"]
    mode = settings.get("fake_tls_mode", "ee")
    domain = settings.get("domain", "azure.microsoft.com")
    client_secret = mode + user["secret"] if mode in ("ee", "dd") else user["secret"]
    from mtproxy_service import build_proxy_link
    tg_link, _ = build_proxy_link(ip, port, client_secret)
    return {"tg_link": tg_link, "node_name": node["name"]}


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
