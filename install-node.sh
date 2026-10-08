#!/usr/bin/env bash
#
# MTProxy 节点 — 一键安装脚本
#
# 在新服务器上运行，把它注册到主面板统一管理：
#   curl -fsSL https://raw.githubusercontent.com/zxcvdyq888-create/mtproxy-panel/main/install-node.sh \
#     | bash -s -- --panel http://主面板IP:8088 --token <安装令牌>
#
# 安装令牌在主面板「服务器」页面点「添加服务器」获取（24 小时有效）。
#
set -euo pipefail

REPO="zxcvdyq888-create/mtproxy-panel"
BRANCH="main"
RAW="https://raw.githubusercontent.com/${REPO}/${BRANCH}"
INSTALL_DIR="/opt/mtproxy-node"
PANEL_DIR="${INSTALL_DIR}/panel"
DATA_DIR="${INSTALL_DIR}/data"
VENV_DIR="${INSTALL_DIR}/venv"
SERVICE="mtproxy-node"
AGENT_PORT="8899"

PANEL_URL=""
INSTALL_TOKEN=""
NODE_NAME=""
PORT_RANGE="10000-20000"

# 支持两种写法：
#   bash install-node.sh <面板地址> <安装令牌> [节点名称]
#   bash install-node.sh --panel <面板地址> --token <安装令牌> [--name 名称]
# 兼容位置参数和 flag 混用：先取位置参数，再解析 flag
if [[ "${1:-}" != "" && "${1:-}" != --* ]]; then
  PANEL_URL="$1"; shift
  if [[ "${1:-}" != "" && "${1:-}" != --* ]]; then INSTALL_TOKEN="$1"; shift; fi
  if [[ "${1:-}" != "" && "${1:-}" != --* ]]; then NODE_NAME="$1"; shift; fi
fi
while [[ $# -gt 0 ]]; do
  case "$1" in
    --panel) PANEL_URL="$2"; shift 2 ;;
    --token) INSTALL_TOKEN="$2"; shift 2 ;;
    --name) NODE_NAME="$2"; shift 2 ;;
    --port-range) PORT_RANGE="$2"; shift 2 ;;
    *) echo "未知参数: $1"; exit 1 ;;
  esac
done

# 缺参数则交互式输入
if [[ -z "$PANEL_URL" ]]; then
  read -rp "主面板地址 (如 http://1.2.3.4:8088): " PANEL_URL
fi
if [[ -z "$INSTALL_TOKEN" ]]; then
  read -rp "安装令牌 (面板「服务器」页面获取): " INSTALL_TOKEN
fi

if [[ -z "$PANEL_URL" || -z "$INSTALL_TOKEN" ]]; then
  echo "用法: curl -fsSL .../install-node.sh | bash -s -- <面板地址> <安装令牌> [节点名称]"
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "请用 root 运行"
  exit 1
fi

if [[ ! -f /etc/debian_version ]]; then
  echo "仅支持 Debian / Ubuntu"
  exit 1
fi

command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl; }

echo "==> [1/6] 安装系统依赖..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip curl iproute2 >/dev/null

echo "==> [2/6] 准备目录..."
mkdir -p "${PANEL_DIR}" "${DATA_DIR}" "${INSTALL_DIR}/proxy"

echo "==> [3/6] 下载节点代码..."
for f in node_agent.py mtproxy_service.py system_monitor.py requirements.txt; do
  curl -fsSL "${RAW}/panel/${f}" -o "${PANEL_DIR}/${f}"
done
echo "    代码下载完成"

echo "==> [4/6] 安装 Python 依赖..."
PYBIN="${VENV_DIR}/bin/python"
if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  if ! python3 -m venv "${VENV_DIR}" 2>/dev/null; then
    echo "    [WARN] venv 创建失败，回退到系统 pip"
    python3 -m pip install -q --upgrade "pip<24" || true
    PYBIN="/usr/bin/python3"
  fi
fi
if [[ "$PYBIN" == "${VENV_DIR}/bin/python" ]]; then
  "${VENV_DIR}/bin/pip" install -q --upgrade pip
  "${VENV_DIR}/bin/pip" install -q fastapi "uvicorn[standard]" psutil
else
  python3 -m pip install -q fastapi "uvicorn[standard]" psutil
fi
echo "$PYBIN" > "${INSTALL_DIR}/.pybin"

# 生成节点 API Token
API_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo -n "$API_TOKEN" > "${DATA_DIR}/api_token"
chmod 600 "${DATA_DIR}/api_token"

# 节点配置
PROXY_PORT="${PROXY_PORT:-443}"
PUBLIC_IP=$(curl -fsSL -4 --max-time 10 https://api.ipify.org 2>/dev/null || echo "")
if [[ -z "$NODE_NAME" ]]; then
  NODE_NAME="node-$(echo "$PUBLIC_IP" | tr '.' '-')"
fi
cat > "${DATA_DIR}/node.json" <<EOF
{"proxy_port": $PROXY_PORT, "domain": "azure.microsoft.com", "fake_tls_mode": "ee", "adtag": ""}
EOF

echo "==> [5/6] 写入 systemd 服务..."
cat > "/etc/systemd/system/${SERVICE}.service" <<EOF
[Unit]
Description=MTProxy Node Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${PANEL_DIR}
Environment=MTP_NODE_DATA=${DATA_DIR}
Environment=MTP_NODE_PORT=${AGENT_PORT}
ExecStart=${PYBIN} -m uvicorn node_agent:app --host 0.0.0.0 --port ${AGENT_PORT}
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
  echo "[ERROR] 节点 agent 启动失败"
  journalctl -u "${SERVICE}" --no-pager -n 20
  exit 1
fi

echo "==> [6/6] 向主面板注册..."
REG_JSON=$(python3 -c "
import json
print(json.dumps({
  'install_token': '''$INSTALL_TOKEN''',
  'name': '''$NODE_NAME''',
  'host': '''$PUBLIC_IP''',
  'agent_port': $AGENT_PORT,
  'api_token': '''$API_TOKEN''',
  'proxy_port': $PROXY_PORT,
  'public_ip': '''$PUBLIC_IP''',
  'port_start': $(echo "$PORT_RANGE" | cut -d- -f1),
  'port_end': $(echo "$PORT_RANGE" | cut -d- -f2),
}))
")
REG_RESP=$(curl -fsSL --max-time 15 -X POST "${PANEL_URL}/api/nodes/register" \
  -H "Content-Type: application/json" -d "$REG_JSON" 2>&1) || {
  echo "[ERROR] 注册失败，请检查面板地址和安装令牌"
  echo "$REG_RESP"
  exit 1
}
echo "    注册成功: $REG_RESP"

echo ""
echo "========================================="
echo "节点安装完成！"
echo "  名称: ${NODE_NAME}"
echo "  公网 IP: ${PUBLIC_IP}"
echo "  Agent 端口: ${AGENT_PORT}"
echo "  代理端口: ${PROXY_PORT}"
echo "去主面板「服务器」页面查看，记得在防火墙放行 ${AGENT_PORT} 和 ${PROXY_PORT} 端口。"
echo "========================================="
