# MTProxy 管理面板

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/)
[![Version](https://img.shields.io/badge/Version-2.1-green.svg)](CHANGELOG.md)

> 发布日期：2026-10-08　|　当前版本：v2.1

Telegram MTProto 代理的多用户 Web 管理面板：用户密钥管理、流量配额、到期自动失效、Fake-TLS 混淆、二维码分享、系统监控，一键脚本完成安装。

## v2.1 更新内容（2026-10-08）

- **更安全**：全新安装生成 16 位随机管理员密码（不再是默认的 admin/admin123）；登录防暴力破解（60 秒 5 次失败自动限流）；JWT 密钥自动生成
- **更快**：添加用户从原来卡 3 秒变成 0.1 秒返回；流量统计、IP 查询加缓存
- **更稳定**：修复 5 个 bug——无推广 TAG 时代理启动崩溃、重启时双进程抢端口、并发操作导致 500 错误、IPv6 链接格式错误、数据库并发写锁死
- **纯 IPv4**：IP 获取、链接生成全部只走 IPv4
- **一键安装**：`install.sh` 全自动装完，Debian 11 旧机器也能装

详细清单见 [CHANGELOG.md](CHANGELOG.md)。

## 界面预览

| 登录 | 仪表盘 |
|---|---|
| ![登录](docs/preview/01-login.png) | ![仪表盘](docs/preview/02-dashboard.png) |

| 用户管理 | 代理设置 |
|---|---|
| ![用户管理](docs/preview/03-users.png) | ![代理设置](docs/preview/04-settings.png) |

## 功能特性

| 模块 | 功能 |
|---|---|
| 用户管理 | 添加 / 删除 / 启用 / 禁用用户，每用户独立密钥与备注 |
| 流量配额 | 按用户统计上行 / 下行 / 总量，超额自动禁用 |
| 到期失效 | 按天设置有效期，到期自动禁用并从代理配置剔除 |
| 分享 | `tg://` 一键链接、`https://t.me/proxy` 链接、二维码扫码导入 |
| 代理控制 | 启动 / 停止 / 重启，运行状态与连接数展示 |
| Fake-TLS | `ee` / `dd` / 关闭三档，伪装域名可配置 |
| 系统监控 | CPU / 内存 / 硬盘实时状态 |
| 面板管理 | 端口修改、管理员改密、明暗主题 |

## 一键安装

要求：Debian 10+ / Ubuntu 20.04+，root 权限，约 100MB 内存。

```bash
curl -fsSL https://raw.githubusercontent.com/zxcvdyq888-create/mtproxy-panel/main/install.sh | bash
```

安装完成后脚本会输出面板地址与**随机生成的管理员密码**（仅显示一次）。

```bash
mtproxy-panel status    # 查看状态
mtproxy-panel logs      # 查看日志
mtproxy-panel restart   # 重启面板
mtproxy-panel uninstall # 卸载（数据保留）
```

- 面板地址：`http://服务器IP:8088`
- 代理端口：默认 `443`（可在面板设置中修改）
- 注意：云服务商安全组需放行面板端口与代理端口

## 使用指南

1. 浏览器打开面板地址，用安装时生成的账号密码登录
2. 「用户」页点「添加用户」，填备注、流量配额（GB）、有效天数
3. 点「分享」复制 `tg://` 链接或展示二维码发给朋友，对方点开即导入 Telegram
4. 用户到期或流量用完会自动禁用；也可在列表中手动启用 / 禁用 / 删除

## 安全说明

- **管理员密码**：全新安装时随机生成 16 位密码并仅显示一次；升级安装不覆盖已有密码。请勿长期使用弱密码，可在面板「设置」中修改
- **登录防护**：JWT 密钥首次启动自动生成并持久化；单 IP 60 秒内 5 次登录失败将被临时限制
- **数据存储**：SQLite 本地存储（WAL 模式），用户密钥文件权限 `600`
- **传输加密**：面板默认 HTTP。如需公网长期暴露面板，建议前置 Nginx/Caddy 反向代理并启用 HTTPS
- **网络**：仅 IPv4

## 架构

```
浏览器 ──► 面板 :8088 ──► FastAPI ──► SQLite
                              │
                              ▼
                     生成 config.py ──► 重启 mtprotoproxy
                                              │
Telegram 客户端 ──► 代理 :443 ────────────────┘
```

- **后端**：Python + FastAPI（`panel/app.py` 路由与认证、`panel/database.py` 数据层、`panel/mtproxy_service.py` 代理进程管理、`panel/system_monitor.py` 系统状态）
- **代理核心**：[alexbers/mtprotoproxy](https://github.com/alexbers/mtprotoproxy)，首次启动自动下载
- **前端**：原生 HTML / CSS / JS 单页应用（`panel/static/`），无框架依赖
- **后台任务**：每 15 秒统计流量、清理过期用户；用户变更后代理在后台重启，接口即时返回

共 15 个 REST 接口，均需 `Authorization: Bearer <token>`（登录接口除外）。

## 常见问题

**Q: 忘记管理员密码？**
A: 服务器上执行：`python3 -c "import sys; sys.path.insert(0,'/opt/mtproxy-panel/panel'); import database as db; db.update_admin('admin','新密码')"`

**Q: 代理启动失败？**
A: `journalctl -u mtproxy-panel -n 50` 看面板日志；`/opt/mtproxy-panel/logs/proxy.log` 看代理日志。常见原因：端口被占用、adtag 格式错误。

**Q: 用户流量不更新？**
A: 统计线程每 15 秒跑一次，稍等；确认代理正在运行。

**Q: 如何备份？**
A: 备份 `/opt/mtproxy-panel/data/panel.db` 即可（含全部用户与配置）。

## 开源协议

[MIT License](LICENSE)
