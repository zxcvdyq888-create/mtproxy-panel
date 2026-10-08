#!/usr/bin/env python3
"""本机端口转发服务：socat TCP 转发，进程管理。"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

DATA_DIR = Path(os.getenv("MTP_DATA_DIR", "/opt/mtproxy-panel/data"))
FORWARD_FILE = DATA_DIR / "forwards.json"

_procs: Dict[int, subprocess.Popen] = {}


def _load() -> Dict[str, Any]:
    try:
        return json.loads(FORWARD_FILE.read_text())
    except Exception:
        return {}


def _save(data: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FORWARD_FILE.write_text(json.dumps(data))


def _socat_ok() -> bool:
    try:
        subprocess.run(["socat", "-V"], capture_output=True, timeout=5)
        return True
    except Exception:
        return False


def _ensure_socat() -> None:
    if not _socat_ok():
        subprocess.run(["apt-get", "update", "-qq"], capture_output=True, timeout=120)
        subprocess.run(["apt-get", "install", "-y", "-qq", "socat"],
                       capture_output=True, timeout=180)


def forward_start(rule_id: int, listen_port: int, target_host: str,
                  target_port: int) -> bool:
    """启动一条转发规则，返回是否成功。"""
    forward_stop(rule_id)
    try:
        _ensure_socat()
        cmd = ["socat",
               f"TCP4-LISTEN:{listen_port},fork,reuseaddr",
               f"TCP4:{target_host}:{target_port}"]
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        _procs[rule_id] = proc
        data = _load()
        data[str(rule_id)] = {
            "listen_port": listen_port,
            "target_host": target_host,
            "target_port": target_port,
            "pid": proc.pid,
        }
        _save(data)
        return True
    except Exception:
        return False


def forward_stop(rule_id: int) -> None:
    """停止一条转发规则。"""
    proc = _procs.pop(rule_id, None)
    if proc and proc.poll() is None:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
    data = _load()
    if str(rule_id) in data:
        del data[str(rule_id)]
        _save(data)


def forward_status() -> Dict[str, Any]:
    """返回所有转发规则状态。"""
    data = _load()
    result = {}
    for rid, info in data.items():
        proc = _procs.get(int(rid))
        result[rid] = {"running": proc is not None and proc.poll() is None, **info}
    return result
