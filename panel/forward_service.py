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
                  target_port: int, protocol: str = "tcp") -> bool:
    """启动一条转发规则，返回是否成功。"""
    forward_stop(rule_id)
    try:
        _ensure_socat()
        proto = (protocol or "tcp").lower()
        procs = []
        if proto in ("tcp", "both"):
            cmd = ["socat",
                   f"TCP4-LISTEN:{listen_port},fork,reuseaddr",
                   f"TCP4:{target_host}:{target_port}"]
            procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
        if proto in ("udp", "both"):
            cmd = ["socat",
                   f"UDP4-LISTEN:{listen_port},fork,reuseaddr",
                   f"UDP4:{target_host}:{target_port}"]
            procs.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL))
        _procs[rule_id] = procs
        data = _load()
        data[str(rule_id)] = {
            "listen_port": listen_port,
            "target_host": target_host,
            "target_port": target_port,
            "protocol": proto,
            "pids": [p.pid for p in procs],
        }
        _save(data)
        return True
    except Exception:
        return False


def forward_stop(rule_id: int) -> None:
    """停止一条转发规则。"""
    procs = _procs.pop(rule_id, None)
    if not isinstance(procs, list):
        procs = [procs] if procs else []
    for proc in procs:
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
        procs = _procs.get(int(rid), [])
        if not isinstance(procs, list):
            procs = [procs]
        alive = any(p is not None and p.poll() is None for p in procs)
        result[rid] = {"running": alive, **info}
    return result
