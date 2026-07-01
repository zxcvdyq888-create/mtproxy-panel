# MTProxy 管理面板

多用户密钥、流量配额、Fake-TLS、二维码分享、系统监控 — Web 管理面板 + 一键安装。

## 一键安装

```bash
curl -fsSL https://raw.githubusercontent.com/zxcvdyq888-create/mtproxy-panel/main/install.sh | bash
```

或使用官方发布地址（推荐，始终最新）：

```bash
curl -fsSL https://Hkt.237700.xyz/mtproxy-release/install.sh | bash
```

安装完成后：

```bash
mtproxy-panel status
```

- 面板地址：`http://服务器IP:8088`
- 默认账号：`admin` / `admin123`（请登录后立即修改）

## 管理命令

```bash
mtproxy-panel start      # 启动
mtproxy-panel stop       # 停止
mtproxy-panel restart    # 重启
mtproxy-panel status     # 状态
mtproxy-panel uninstall  # 卸载
```

## 功能

- 多用户密钥管理（添加 / 删除 / 禁用 / 备注）
- 流量配额 + 到期自动失效
- Fake-TLS 混淆（ee / dd / 关闭）
- tg:// 链接 + 二维码分享
- 系统监控（CPU / 内存 / 硬盘）
- 管理员改密、面板端口配置

## 维护者：推送到 GitHub

```bash
export GITHUB_TOKEN=ghp_你的Token
bash scripts/publish-github.sh
bash scripts/github-release.sh v1.0.1
unset GITHUB_TOKEN
```

详细图文教程见服务器文件：`/root/GitHub项目发布完整教程.md`

## 仓库信息

- GitHub: https://github.com/zxcvdyq888-create/mtproxy-panel
- 安装目录: `/opt/mtproxy-panel`