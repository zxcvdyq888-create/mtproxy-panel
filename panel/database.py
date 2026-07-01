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
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_proxy_users_enabled ON proxy_users(enabled);
            """
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
    settings = get_all_settings()
    if username != settings.get("admin_user", "admin"):
        return False
    stored = settings.get("admin_pass_hash", "")
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
            (remark, secret, enabled, traffic_limit_gb, expires_at, created_at)
            VALUES (?, ?, 1, ?, ?, ?)
            """,
            (remark, secret, traffic_limit_gb, expires_at, _utc_now()),
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
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE proxy_users
            SET upload_bytes = upload_bytes + ?,
                download_bytes = download_bytes + ?
            WHERE id = ?
            """,
            (upload, download, user_id),
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