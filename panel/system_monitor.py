from __future__ import annotations

import shutil
from typing import Any, Dict

import psutil


def get_system_status() -> Dict[str, Any]:
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = shutil.disk_usage("/")

    return {
        "cpu_percent": round(cpu, 1),
        "memory_percent": round(mem.percent, 1),
        "memory_used_gb": round(mem.used / 1024 ** 3, 2),
        "memory_total_gb": round(mem.total / 1024 ** 3, 2),
        "disk_percent": round(disk.used / disk.total * 100, 1),
        "disk_free_gb": round(disk.free / 1024 ** 3, 2),
        "disk_total_gb": round(disk.total / 1024 ** 3, 2),
    }