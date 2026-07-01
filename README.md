# MTProxy 管理面板

多用户密钥、流量配额、Fake-TLS、二维码分享、系统监控 — 一键安装 Web 管理面板。

## 一键安装（任意服务器，root 执行）

把 `YOUR_USERNAME` 换成你的 GitHub 用户名后执行：

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/mtproxy-panel/main/install.sh | bash
```

安装完成后：

```bash
mtproxy-panel status
```

默认面板：`http://服务器IP:8088`，账号 `admin` / `admin123`（登录后请立即改密）。

## 管理命令

```bash
mtproxy-panel start      # 启动
mtproxy-panel stop       # 停止
mtproxy-panel restart    # 重启
mtproxy-panel status     # 状态
mtproxy-panel uninstall  # 卸载
```

## 发布到 GitHub（维护者）

1. 修改 `install.sh` 里的 `DEFAULT_GITHUB_REPO="YOUR_USERNAME/mtproxy-panel"`
2. 推送代码到 GitHub
3. 打标签触发 Release（可选，加速下载）：

```bash
git tag v1.0.0 && git push origin v1.0.0
```

或在 GitHub 网页 **Actions → Release → Run workflow** 手动发布。

## 自定义下载源

```bash
export MTP_GITHUB_REPO=你的用户名/mtproxy-panel
curl -fsSL https://raw.githubusercontent.com/你的用户名/mtproxy-panel/main/install.sh | bash
```

或使用自建服务器：

```bash
export MTP_RELEASE_URL=https://你的域名/mtproxy-release
curl -fsSL https://你的域名/mtproxy-release/install.sh | bash
```