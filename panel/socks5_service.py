#!/usr/bin/env python3
"""SOCKS5 代理服务端（asyncio 实现）。

特性：
  - 用户名/密码认证（用户名为 user{id}，密码为用户的 socks_password）
  - 仅支持 CONNECT 命令（TCP），IPv4 only
  - 流量计入用户 upload/download
"""
from __future__ import annotations

import asyncio
import logging
import os
import struct
from pathlib import Path
from typing import Dict, Optional, Tuple

logger = logging.getLogger("socks5")

# 独立进程运行时需要能 import database
import sys
sys.path.insert(0, str(Path(__file__).parent))
import database as db


async def _read_exact(reader: asyncio.StreamReader, n: int) -> bytes:
    data = await reader.readexactly(n)
    return data


async def handle_client(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    user_id: Optional[int] = None
    try:
        # ---- 握手：VER, NMETHODS, METHODS ----
        ver, nmethods = struct.unpack("!BB", await _read_exact(reader, 2))
        if ver != 5:
            writer.close()
            return
        methods = await _read_exact(reader, nmethods)
        # 只支持用户名密码认证 (0x02)
        if 0x02 not in methods:
            writer.write(struct.pack("!BB", 5, 0xFF))
            await writer.drain()
            writer.close()
            return
        writer.write(struct.pack("!BB", 5, 0x02))
        await writer.drain()

        # ---- 认证：VER(0x01), ULEN, UNAME, PLEN, PASSWD ----
        aver = (await _read_exact(reader, 1))[0]
        if aver != 1:
            writer.close()
            return
        ulen = (await _read_exact(reader, 1))[0]
        username = (await _read_exact(reader, ulen)).decode("utf-8", "ignore")
        plen = (await _read_exact(reader, 1))[0]
        password = (await _read_exact(reader, plen)).decode("utf-8", "ignore")

        user_id = _auth_user(username, password)
        if user_id is None:
            writer.write(struct.pack("!BB", 1, 0x01))
            await writer.drain()
            writer.close()
            return
        writer.write(struct.pack("!BB", 1, 0x00))
        await writer.drain()

        # ---- 请求：VER, CMD, RSV, ATYP, DST.ADDR, DST.PORT ----
        ver, cmd, rsv, atyp = struct.unpack("!BBBB", await _read_exact(reader, 4))
        if ver != 5 or cmd != 1:  # 只支持 CONNECT
            writer.write(struct.pack("!BBBBIH", 5, 0x07, 0, 1, 0, 0))
            await writer.drain()
            writer.close()
            return

        if atyp == 1:  # IPv4
            addr = ".".join(str(b) for b in await _read_exact(reader, 4))
        elif atyp == 3:  # 域名
            alen = (await _read_exact(reader, 1))[0]
            addr = (await _read_exact(reader, alen)).decode("utf-8", "ignore")
        else:  # 不支持 IPv6
            writer.write(struct.pack("!BBBBIH", 5, 0x08, 0, 1, 0, 0))
            await writer.drain()
            writer.close()
            return
        port = struct.unpack("!H", await _read_exact(reader, 2))[0]

        # ---- 连接目标 ----
        try:
            remote_reader, remote_writer = await asyncio.wait_for(
                asyncio.open_connection(addr, port), timeout=10
            )
        except Exception:
            writer.write(struct.pack("!BBBBIH", 5, 0x05, 0, 1, 0, 0))
            await writer.drain()
            writer.close()
            return

        # 成功
        writer.write(struct.pack("!BBBBIH", 5, 0x00, 0, 1, 0, 0))
        await writer.drain()

        # ---- 双向转发 + 流量统计 ----
        await _relay(reader, writer, remote_reader, remote_writer, user_id)

    except (asyncio.IncompleteReadError, ConnectionResetError):
        pass
    except Exception as e:
        logger.warning(f"SOCKS5 处理异常: {e}")
    finally:
        try:
            writer.close()
        except Exception:
            pass


def _auth_user(username: str, password: str) -> Optional[int]:
    """验证 SOCKS5 用户，返回 user_id。用户名格式：user{id}。"""
    if not username.startswith("user"):
        return None
    try:
        user_id = int(username[4:])
    except ValueError:
        return None
    user = db.get_user(user_id)
    if not user or not user.get("enabled"):
        return None
    import secrets as _secrets
    expected = user.get("socks_password") or ""
    if not expected or not _secrets.compare_digest(expected, password):
        return None
    return user_id


async def _relay(client_r, client_w, remote_r, remote_w, user_id: int) -> None:
    up_bytes = 0
    down_bytes = 0

    async def _forward(src, dst, count_up: bool):
        nonlocal up_bytes, down_bytes
        try:
            while True:
                data = await src.read(65536)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
                if count_up:
                    up_bytes += len(data)
                else:
                    down_bytes += len(data)
        except Exception:
            pass
        finally:
            try:
                dst.close()
            except Exception:
                pass

    await asyncio.gather(
        _forward(client_r, remote_w, True),
        _forward(remote_r, client_w, False),
    )
    # 流量计入用户（复用 last_seen 更新逻辑）
    if up_bytes or down_bytes:
        try:
            db.add_traffic(user_id, up_bytes, down_bytes)
        except Exception:
            pass


async def main() -> None:
    port = int(os.getenv("SOCKS5_PORT", "1080"))
    server = await asyncio.start_server(handle_client, "0.0.0.0", port)
    logger.warning(f"SOCKS5 代理启动，端口 {port}")
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    asyncio.run(main())
