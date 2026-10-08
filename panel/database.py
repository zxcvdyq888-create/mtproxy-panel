from __future__ import annotations

import os
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import bcrypt

DATA_DIR = Path(os.getenv("MTP_PANEL_DATA", "/opt/mtproxy-panel/data"))
DB_PATH = DATA_DIR / "panel.db"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with get_conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS proxy_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                remark TEXT NOT NULL DEFAULT '',
                secret TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                traffic_limit_gb REAL NOT NULL DEFAULT 0,
                upload_bytes INTEGER NOT NULL DEFAULT 0,
                download_bytes INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                created_at TEXT NOT NULL,
                last_seen TEXT,
                socks_password TEXT NOT NULL DEFAULT ''
            );

            CREATE INDEX IF NOT EXISTS idx_proxy_users_enabled ON proxy_users(enabled);

            CREATE TABLE IF NOT EXISTS nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                host TEXT NOT NULL,
                agent_port INTEGER NOT NULL DEFAULT 8899,
                api_token TEXT NOT NULL,
                proxy_port INTEGER NOT NULL DEFAULT 443,
                public_ip TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'offline',
                last_seen TEXT,
                cpu_percent REAL NOT NULL DEFAULT 0,
                mem_percent REAL NOT NULL DEFAULT 0,
                proxy_running INTEGER NOT NULL DEFAULT 0,
                node_user_count INTEGER NOT NULL DEFAULT 0,
                port_start INTEGER NOT NULL DEFAULT 10000,
                port_end INTEGER NOT NULL DEFAULT 20000,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS forward_rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                rule_type TEXT NOT NULL DEFAULT 'port',
                listen_node_id INTEGER NOT NULL DEFAULT 0,
                listen_port INTEGER NOT NULL,
                target_host TEXT NOT NULL DEFAULT '',
                target_port INTEGER NOT NULL,
                chain_id INTEGER NOT NULL DEFAULT 0,
                chain_order INTEGER NOT NULL DEFAULT 0,
                protocol TEXT NOT NULL DEFAULT 'tcp',
                user_id INTEGER NOT NULL DEFAULT 0,
                speed_limit_mbps INTEGER NOT NULL DEFAULT 0,
                traffic_limit_gb REAL NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                running INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS forward_chains (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL DEFAULT '',
                in_node_id INTEGER NOT NULL DEFAULT 0,
                out_node_id INTEGER NOT NULL DEFAULT 0,
                protocol TEXT NOT NULL DEFAULT 'tcp',
                user_id INTEGER NOT NULL DEFAULT 0,
                speed_limit_mbps INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            """
        )
        # 隧道表补出入口机器
        for _col, _def in [
            ("in_node_id", "INTEGER NOT NULL DEFAULT 0"),
            ("out_node_id", "INTEGER NOT NULL DEFAULT 0"),
            ("protocol", "TEXT NOT NULL DEFAULT 'tcp'"),
            ("user_id", "INTEGER NOT NULL DEFAULT 0"),
            ("speed_limit_mbps", "INTEGER NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE forward_chains ADD COLUMN {_col} {_def}")
            except sqlite3.OperationalError:
                pass
        # 节点表补端口范围
        for _col, _def in [
            ("port_start", "INTEGER NOT NULL DEFAULT 10000"),
            ("port_end", "INTEGER NOT NULL DEFAULT 20000"),
        ]:
            try:
                conn.execute(f"ALTER TABLE nodes ADD COLUMN {_col} {_def}")
            except sqlite3.OperationalError:
                pass
        # 转发表补新字段（隧道化升级）
        for _col, _def in [
            ("protocol", "TEXT NOT NULL DEFAULT 'tcp'"),
            ("user_id", "INTEGER NOT NULL DEFAULT 0"),
            ("speed_limit_mbps", "INTEGER NOT NULL DEFAULT 0"),
            ("traffic_limit_gb", "REAL NOT NULL DEFAULT 0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE forward_rules ADD COLUMN {_col} {_def}")
            except sqlite3.OperationalError:
                pass
        # 存量库迁移：补 last_seen 列
        try:
            conn.execute("ALTER TABLE proxy_users ADD COLUMN last_seen TEXT")
        except sqlite3.OperationalError:
            pass  # 列已存在
        # 存量库迁移：补 socks_password 列
        try:
            conn.execute("ALTER TABLE proxy_users ADD COLUMN socks_password TEXT NOT NULL DEFAULT ''")
        except sqlite3.OperationalError:
            pass  # 列已存在
        # 给没有 socks_password 的老用户生成
        for row in conn.execute("SELECT id FROM proxy_users WHERE socks_password = ''").fetchall():
            conn.execute(
                "UPDATE proxy_users SET socks_password = ? WHERE id = ?",
                (secrets.token_urlsafe(12), row["id"]),
            )

        defaults = {
            "panel_port": "8088",
            "admin_user": "admin",
            "admin_pass_hash": "",
            "proxy_port": "443",
            "stat_port": "8888",
            "domain": "azure.microsoft.com",
            "fake_tls_mode": "ee",
            "adtag": "",
            "public_ip": "",
            "provider": "python",
            "socks5_enabled": "0",
            "socks5_port": "1080",
        }
        for key, value in defaults.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'admin_pass_hash'"
        ).fetchone()
        if not row or not row["value"]:
            default_hash = bcrypt.hashpw(
                b"admin123", bcrypt.gensalt()
            ).decode()
            conn.execute(
                "UPDATE settings SET value = ? WHERE key = 'admin_pass_hash'",
                (default_hash,),
            )


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        # WAL: 读写并发不锁死；busy_timeout: 冲突时等待重试而不是直接报错
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def get_all_settings() -> Dict[str, str]:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}


def verify_admin(username: str, password: str) -> bool:
    if username != get_setting("admin_user", "admin"):
        return False
    stored = get_setting("admin_pass_hash", "")
    if not stored:
        return False
    return bcrypt.checkpw(password.encode(), stored.encode())


def update_admin(username: str, password: str) -> None:
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    set_setting("admin_user", username)
    set_setting("admin_pass_hash", password_hash)


def gen_secret() -> str:
    return secrets.token_hex(16)


def list_users() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM proxy_users ORDER BY id ASC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM proxy_users WHERE id = ?", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def create_user(
    remark: str,
    traffic_limit_gb: float = 0,
    expires_days: Optional[int] = None,
) -> Dict[str, Any]:
    secret = gen_secret()
    expires_at = None
    if expires_days and expires_days > 0:
        expires_at = datetime.now(timezone.utc).timestamp() + expires_days * 86400
        expires_at = datetime.fromtimestamp(expires_at, timezone.utc).isoformat()

    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO proxy_users
            (remark, secret, enabled, traffic_limit_gb, expires_at, created_at, socks_password)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            """,
            (remark, secret, traffic_limit_gb, expires_at, _utc_now(), secrets.token_urlsafe(12)),
        )
        user_id = cur.lastrowid
    return get_user(user_id)  # type: ignore


def update_user(user_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    allowed = {
        "remark",
        "enabled",
        "traffic_limit_gb",
        "expires_at",
        "upload_bytes",
        "download_bytes",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_user(user_id)

    cols = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [user_id]
    with get_conn() as conn:
        conn.execute(f"UPDATE proxy_users SET {cols} WHERE id = ?", values)
    return get_user(user_id)


def delete_user(user_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM proxy_users WHERE id = ?", (user_id,))
        return cur.rowcount > 0


def add_traffic(user_id: int, upload: int, download: int) -> None:
    """累加流量；有流量增量即视为活跃，更新最后在线时间。"""
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE proxy_users
            SET upload_bytes = upload_bytes + ?,
                download_bytes = download_bytes + ?,
                last_seen = ?
            WHERE id = ?
            """,
            (upload, download, _utc_now(), user_id),
        )


def disable_expired_and_over_quota() -> int:
    changed = 0
    now = datetime.now(timezone.utc)
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM proxy_users WHERE enabled = 1").fetchall()
        for row in rows:
            disable = False
            if row["expires_at"]:
                try:
                    exp = datetime.fromisoformat(row["expires_at"])
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    if now >= exp:
                        disable = True
                except ValueError:
                    pass
            limit_gb = row["traffic_limit_gb"] or 0
            if limit_gb > 0:
                used = row["upload_bytes"] + row["download_bytes"]
                if used >= int(limit_gb * 1024 ** 3):
                    disable = True
            if disable:
                conn.execute(
                    "UPDATE proxy_users SET enabled = 0 WHERE id = ?",
                    (row["id"],),
                )
                changed += 1
    return changed


def ensure_default_user_from_legacy(secret: str, remark: str = "默认用户") -> None:
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM proxy_users").fetchone()["c"]
        if count > 0:
            return
        conn.execute(
            """
            INSERT INTO proxy_users
            (remark, secret, enabled, traffic_limit_gb, created_at)
            VALUES (?, ?, 1, 0, ?)
            """,
            (remark, secret, _utc_now()),
        )


# ============ 节点管理 ============

def list_nodes() -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM nodes ORDER BY id ASC").fetchall()
        return [dict(row) for row in rows]


def get_node(node_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row) if row else None


def create_node(name: str, host: str, agent_port: int, api_token: str,
                proxy_port: int = 443, public_ip: str = "",
                port_start: int = 10000, port_end: int = 20000) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO nodes
            (name, host, agent_port, api_token, proxy_port, public_ip,
             port_start, port_end, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (name, host, agent_port, api_token, proxy_port, public_ip,
             port_start, port_end, _utc_now()),
        )
        node_id = cur.lastrowid
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return dict(row)


def delete_node(node_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
        return cur.rowcount > 0


def update_node_status(node_id: int, status: str, stats: Optional[Dict[str, Any]] = None) -> None:
    stats = stats or {}
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE nodes SET status = ?, last_seen = ?,
                cpu_percent = ?, mem_percent = ?,
                proxy_running = ?, node_user_count = ?
            WHERE id = ?
            """,
            (
                status,
                _utc_now() if status == "online" else None,
                stats.get("cpu_percent", 0),
                stats.get("mem_percent", 0),
                1 if stats.get("proxy_running") else 0,
                stats.get("user_count", 0),
                node_id,
            ),
        )


def get_install_token() -> str:
    """获取安装令牌（不存在或过期则生成新的，有效期 24 小时）。"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'install_token'"
        ).fetchone()
        exp_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'install_token_exp'"
        ).fetchone()
        now_ts = datetime.now(timezone.utc).timestamp()
        if row and exp_row and float(exp_row["value"]) > now_ts:
            return row["value"]
        token = secrets.token_urlsafe(24)
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('install_token', ?)",
            (token,),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('install_token_exp', ?)",
            (str(now_ts + 86400),),
        )
        return token


def verify_install_token(token: str) -> bool:
    if not token:
        return False
    with get_conn() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = 'install_token'"
        ).fetchone()
        exp_row = conn.execute(
            "SELECT value FROM settings WHERE key = 'install_token_exp'"
        ).fetchone()
        if not row or not exp_row:
            return False
        now_ts = datetime.now(timezone.utc).timestamp()
        return secrets.compare_digest(row["value"], token) and float(exp_row["value"]) > now_ts


def update_node(node_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    allowed = {"name", "proxy_port", "public_ip", "domain"}
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return get_node(node_id)
    # nodes 表没有 domain 列，存到 public_ip 同级的扩展字段——这里用内存+推送，持久化到 settings 风格的 node_meta 表
    cols = ", ".join(f"{k} = ?" for k in updates if k in ("name", "proxy_port", "public_ip"))
    values = [v for k, v in updates.items() if k in ("name", "proxy_port", "public_ip")]
    with get_conn() as conn:
        if cols:
            conn.execute(f"UPDATE nodes SET {cols} WHERE id = ?", values + [node_id])
        if "domain" in updates:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS node_meta
                   (node_id INTEGER PRIMARY KEY, domain TEXT)"""
            )
            conn.execute(
                "INSERT OR REPLACE INTO node_meta (node_id, domain) VALUES (?, ?)",
                (node_id, updates["domain"]),
            )
    return get_node(node_id)


def get_node_domain(node_id: int) -> str:
    with get_conn() as conn:
        try:
            row = conn.execute(
                "SELECT domain FROM node_meta WHERE node_id = ?", (node_id,)
            ).fetchone()
        except sqlite3.OperationalError:
            return ""
        return row["domain"] if row else ""

# ============ 转发规则 ============
def create_forward_rule(name: str, rule_type: str, listen_node_id: int, listen_port: int,
                       target_host: str, target_port: int, chain_id: int = 0,
                       chain_order: int = 0, protocol: str = "tcp", user_id: int = 0,
                       speed_limit_mbps: int = 0, traffic_limit_gb: float = 0) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO forward_rules
               (name, rule_type, listen_node_id, listen_port, target_host, target_port,
                chain_id, chain_order, protocol, user_id, speed_limit_mbps,
                traffic_limit_gb, enabled, running, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?)""",
            (name, rule_type, listen_node_id, listen_port, target_host, target_port,
             chain_id, chain_order, protocol, user_id, speed_limit_mbps,
             traffic_limit_gb, _utc_now()))
        rid = cur.lastrowid
        conn.commit()
    return get_forward_rule(rid)

def get_forward_rule(rule_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM forward_rules WHERE id=?", (rule_id,)).fetchone()
        return dict(row) if row else None

def list_forward_rules() -> list:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM forward_rules ORDER BY chain_id, chain_order, id").fetchall()
        return [dict(r) for r in rows]

def update_forward_rule(rule_id: int, **fields: Any) -> Optional[Dict[str, Any]]:
    allowed = {"name", "listen_node_id", "listen_port", "target_host", "target_port",
               "enabled", "running", "chain_id", "chain_order", "protocol",
               "user_id", "speed_limit_mbps", "traffic_limit_gb"}
    sets = {k: v for k, v in fields.items() if k in allowed}
    if not sets:
        return get_forward_rule(rule_id)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE forward_rules SET {', '.join(f'{k}=?' for k in sets)} WHERE id=?",
            (*sets.values(), rule_id))
        conn.commit()
    return get_forward_rule(rule_id)

def delete_forward_rule(rule_id: int) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM forward_rules WHERE id=?", (rule_id,))
        conn.commit()
        return cur.rowcount > 0

def create_forward_chain(name: str, in_node_id: int = 0, out_node_id: int = 0,
                       protocol: str = "tcp", user_id: int = 0,
                       speed_limit_mbps: int = 0) -> Dict[str, Any]:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO forward_chains "
            "(name, in_node_id, out_node_id, protocol, user_id, "
            "speed_limit_mbps, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, in_node_id, out_node_id, protocol, user_id,
             speed_limit_mbps, _utc_now()))
        cid = cur.lastrowid
        conn.commit()
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM forward_chains WHERE id=?", (cid,)).fetchone()
        return dict(row)

def list_forward_chains() -> list:
    with get_conn() as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM forward_chains ORDER BY id DESC").fetchall()
        return [dict(r) for r in rows]

def delete_forward_chain(chain_id: int) -> bool:
    with get_conn() as conn:
        conn.execute("DELETE FROM forward_rules WHERE chain_id=?", (chain_id,))
        cur = conn.execute("DELETE FROM forward_chains WHERE id=?", (chain_id,))
        conn.commit()
        return cur.rowcount > 0
