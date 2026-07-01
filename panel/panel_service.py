from __future__ import annotations

import os
import subprocess
from pathlib import Path

INSTALL_DIR = Path(os.getenv("MTP_INSTALL_DIR", "/opt/mtproxy-panel"))
SERVICE_NAME = "mtproxy-panel"


def get_panel_port_from_unit() -> int | None:
    unit = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
    if not unit.exists():
        return None
    for line in unit.read_text().splitlines():
        if "--port" in line:
            parts = line.split("--port")
            if len(parts) > 1:
                try:
                    return int(parts[1].strip().split()[0])
                except ValueError:
                    pass
    return None


def apply_panel_port(port: int) -> bool:
    unit_path = Path(f"/etc/systemd/system/{SERVICE_NAME}.service")
    if not unit_path.exists():
        return False

    content = unit_path.read_text()
    import re

    new_content, n = re.subn(
        r"(--port\s+)\d+",
        rf"\g<1>{port}",
        content,
    )
    if n == 0:
        return False

    unit_path.write_text(new_content)
    subprocess.run(["systemctl", "daemon-reload"], check=False)
    subprocess.run(["systemctl", "restart", SERVICE_NAME], check=False)
    return True


def is_port_available(port: int) -> bool:
    try:
        result = subprocess.run(
            ["ss", "-H", "-lnt", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return not result.stdout.strip()
    except Exception:
        return True