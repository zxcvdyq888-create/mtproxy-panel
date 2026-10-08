#!/usr/bin/env bash
#
# MTProxy 管理面板 — 一键安装脚本（优化版 v2.1）
#
# 用法：
#   curl -fsSL https://raw.githubusercontent.com/zxcvdyq888-create/mtproxy-panel/main/install.sh | bash
#
# 装完得到：
#   - Web 面板：http://服务器IP:8088（默认账号 admin / admin123，登录后立即修改）
#   - MTProto 代理自动启动（默认 443 端口，Fake-TLS ee 模式）
#   - 管理命令：mtproxy-panel {status|start|stop|restart|logs|uninstall}
#
set -euo pipefail

REPO="zxcvdyq888-create/mtproxy-panel"
BRANCH="main"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
INSTALL_DIR="/opt/mtproxy-panel"
PANEL_DIR="${INSTALL_DIR}/panel"
DATA_DIR="${INSTALL_DIR}/data"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE="mtproxy-panel"
PANEL_PORT="8088"

# ---------- 0. 基础检查 ----------
if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行：sudo bash $0"
  exit 1
fi

if [[ ! -f /etc/debian_version ]]; then
  echo "仅支持 Debian / Ubuntu"
  exit 1
fi

command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl; }
command -v ss >/dev/null || { apt-get update -qq && apt-get install -y -qq iproute2; }

echo "==> [1/7] 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl iproute2 >/dev/null

# ---------- 2. 目录 ----------
echo "==> [2/7] 准备目录..."
mkdir -p "${PANEL_DIR}" "${DATA_DIR}" "${INSTALL_DIR}/proxy"

# ---------- 3. 下载面板代码 ----------
echo "==> [3/7] 下载面板代码（${REPO}@${BRANCH}）..."
for f in app.py database.py mtproxy_service.py panel_service.py system_monitor.py requirements.txt; do
  curl -fsSL "${RAW}/panel/${f}" -o "${PANEL_DIR}/${f}"
done
mkdir -p "${PANEL_DIR}/static"
for f in index.html app.js style.css; do
  curl -fsSL "${RAW}/panel/static/${f}" -o "${PANEL_DIR}/static/${f}"
done
echo "    代码下载完成"

# ---------- 4. Python 虚拟环境 ----------
echo "==> [4/7] 安装 Python 依赖..."
# Debian 11 旧源 python3-venv 依赖损坏时回退到系统 pip
PYBIN="${VENV_DIR}/bin/python"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  if ! python3 -m venv "${VENV_DIR}" 2>/dev/null; then
    echo "    [WARN] venv 创建失败（Debian 11 旧源常见），回退到系统 pip"
    python3 -m pip install -q --upgrade "pip<24" || true
    PYBIN="/usr/bin/python3"
  fi
fi
if [[ "$PYBIN" == "${VENV_DIR}/bin/python" ]]; then
  "${VENV_DIR}/bin/pip" install -q --upgrade pip
  "${VENV_DIR}/bin/pip" install -q -r "${PANEL_DIR}/requirements.txt"
else
  python3 -m pip install -q -r "${PANEL_DIR}/requirements.txt"
fi
echo "$PYBIN" > "${INSTALL_DIR}/.pybin"
echo "    依赖安装完成"

# ---------- 5. systemd 服务 ----------
echo "==> [5/7] 写入 systemd 服务..."
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=MTProxy Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
WorkingDirectory=${PANEL_DIR}
Environment=MTP_PANEL_DATA=${DATA_DIR}
Environment=MTP_INSTALL_DIR=${INSTALL_DIR}
ExecStart=${PYBIN} -m uvicorn app:app --host 0.0.0.0 --port ${PANEL_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable -q "${SERVICE}"
systemctl restart "${SERVICE}"
sleep 3

if ! systemctl is-active -q "${SERVICE}"; then
  echo "面板启动失败，查看日志：journalctl -u ${SERVICE} -n 50"
  exit 1
fi
echo "    面板已启动"

# ---------- 6. 启动 MTProto 代理 ----------
echo "==> [6/7] 启动 MTProto 代理（首次会下载代理核心，约 1 分钟）..."
# 全新安装时生成随机管理员密码，消除默认密码风险；升级安装不覆盖已有密码
FRESH_INSTALL=0
[[ ! -f "${DATA_DIR}/panel.db" ]] && FRESH_INSTALL=1
if [[ "$FRESH_INSTALL" = 1 ]]; then
  ADMIN_PASS="$(tr -dc 'A-Za-z0-9' < /dev/urandom | head -c 16)"
  export ADMIN_PASS
fi
"${PYBIN}" - <<'PYEOF'
import os, sys
sys.path.insert(0, "/opt/mtproxy-panel/panel")
import database as db
db.init_db()
if os.environ.get("ADMIN_PASS"):
    db.update_admin("admin", os.environ["ADMIN_PASS"])
from mtproxy_service import start_proxy
ok = start_proxy()
print("PROXY_STARTED" if ok else "PROXY_FAILED")
PYEOF

# ---------- 7. 管理命令 ----------
echo "==> [7/7] 安装管理命令..."
cat > /usr/local/bin/mtproxy-panel <<'EOF'
#!/usr/bin/env bash
SERVICE="mtproxy-panel"
case "${1:-status}" in
  start)   systemctl start "$SERVICE" ;;
  stop)    systemctl stop "$SERVICE" ;;
  restart) systemctl restart "$SERVICE" ;;
  status)  systemctl status "$SERVICE" --no-pager -l | head -20 ;;
  logs)    journalctl -u "$SERVICE" -n 100 --no-pager ;;
  uninstall)
    read -rp "确认卸载？数据目录 /opt/mtproxy-panel/data 将保留 [y/N] " c
    [[ "$c" == "y" ]] || exit 0
    systemctl stop "$SERVICE" 2>/dev/null || true
    systemctl disable "$SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE}.service"
    systemctl daemon-reload
    rm -rf /opt/mtproxy-panel/panel /opt/mtproxy-panel/venv /opt/mtproxy-panel/proxy
    rm -f /usr/local/bin/mtproxy-panel
    echo "已卸载（数据保留在 /opt/mtproxy-panel/data）"
    ;;
  *) echo "用法：mtproxy-panel {start|stop|restart|status|logs|uninstall}" ;;
esac
EOF
chmod +x /usr/local/bin/mtproxy-panel

# ---------- 完成 ----------
PUB_IP=$(curl -fsSL --ipv4 --connect-timeout 5 https://api.ip.sb/ip 2>/dev/null || echo "服务器IP")
echo ""
echo "=============================================="
echo " MTProxy 管理面板安装完成"
echo "=============================================="
echo " 面板地址：http://${PUB_IP}:${PANEL_PORT}"
if [[ -n "${ADMIN_PASS:-}" ]]; then
  echo " 管理员账号：admin"
  echo " 管理员密码：${ADMIN_PASS}"
  echo " （随机生成，仅显示一次，请妥善保存）"
else
  echo " 管理员账号：沿用已有密码（升级安装未改动）"
fi
echo ""
echo " 常用命令："
echo "   mtproxy-panel status    查看状态"
echo "   mtproxy-panel logs      查看日志"
echo "   mtproxy-panel restart   重启面板"
echo "   mtproxy-panel uninstall 卸载"
echo ""
echo " 注意：云服务商安全组需放行 ${PANEL_PORT}（面板）与代理端口（默认 443）"
echo "=============================================="
