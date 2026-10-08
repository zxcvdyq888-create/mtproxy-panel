# 更新日志

## v2.1（2026-10-08）

### 安全
- JWT 密钥首次启动自动生成随机值并持久化（此前为硬编码默认值，可伪造 token）
- 登录限流：单 IP 60 秒内 5 次失败后临时限制
- 全新安装时生成 16 位随机管理员密码并仅显示一次（替代默认 admin/admin123）
- 代理配置文件 `config.py` 权限设为 `600`
- 手动填写的公网 IP 强制校验 IPv4

### 可靠性修复
- 修复：未设置 adtag 时生成 `AD_TAG = None` 导致代理启动崩溃
- 修复：`stop_proxy` 只等待 1 秒，旧进程未退出即起新进程，双进程抢端口（已删用户仍可连接）
- 修复：并发启停竞态（后台重启撞上手动启动，抢 zip 文件导致 API 500），`RLock` 互斥
- 修复：IPv6 地址的 `tg://` 链接缺少方括号导致客户端无法解析
- `stop_proxy` 增加 PID 复用校验，防止误杀其他进程

### 性能
- 代理重启 / 用户增删改 / 设置保存改为后台任务，接口从 ~3 秒降至 0.1 秒返回
- 公网 IP 缓存 10 分钟（此前每次请求 fork 一个 curl）
- 代理日志解析增加文件指纹缓存（此前每次扫描 300KB 日志）
- SQLite 启用 WAL + `busy_timeout=5000`，消除并发写 `database is locked`
- 统计线程异常写入日志（此前静默吞掉）

### 网络
- IPv4 only：IP 获取、IP 校验、链接生成全部只走 IPv4

### 安装
- 新增 `install.sh` 一键安装脚本（依赖安装 → 代码拉取 → venv → systemd → 启动）
- Debian 11 旧源 `python3-venv` 损坏时自动回退到系统 pip
- `mtproxy-panel` 管理命令：start / stop / restart / status / logs / uninstall
