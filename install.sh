#!/bin/bash
# ============================================================
#  MTProxy 管理面板 · 一键安装脚本 v2.0
#  功能：多用户密钥 | 流量配额 | Fake-TLS | 二维码分享 | 系统监控
#  风格：仿 mtproxy.sh · 子命令管理 · 脚本常驻
# ============================================================

set -euo pipefail
export LANG=en_US.UTF-8
export LC_ALL=en_US.UTF-8

# curl | bash 时 stdin 是脚本管道，强制非交互安装
if [[ -p /dev/stdin ]]; then
    export MTP_NONINTERACTIVE=1
fi

INSTALL_DIR="/opt/mtproxy-panel"
PANEL_DIR="$INSTALL_DIR/panel"
DATA_DIR="$INSTALL_DIR/data"
SERVICE_NAME="mtproxy-panel"
SCRIPT_PATH="$(readlink -f "$0" 2>/dev/null || realpath "$0" 2>/dev/null || echo "$0")"

PUBLIC_IP=""
PANEL_PORT=8088
PROXY_PORT=34286
FAKE_DOMAIN="www.google.com"
FAKE_TLS_MODE="ee"
FAKE_DOMAIN_CANDIDATES=(
    "www.google.com"
    "www.microsoft.com"
    "www.cloudflare.com"
    "azure.microsoft.com"
    "www.apple.com"
)

# GitHub 仓库（格式: 用户名/仓库名）— 推送到 GitHub 后改成你的
DEFAULT_GITHUB_REPO="zxcvdyq888-create/mtproxy-panel"
MTP_GITHUB_REPO="${MTP_GITHUB_REPO:-$DEFAULT_GITHUB_REPO}"

github_owner() { echo "${MTP_GITHUB_REPO%%/*}"; }
github_repo()  { echo "${MTP_GITHUB_REPO##*/}"; }

# 官方发布地址（最新版，GitHub 仅作备用源码仓库）
DEFAULT_RELEASE_URL="https://Hkt.237700.xyz/mtproxy-release"
RELEASE_BASE="${MTP_RELEASE_URL:-$DEFAULT_RELEASE_URL}"

install_cmd_hint() {
    echo "curl -fsSL ${RELEASE_BASE}/install.sh | bash"
}

# ==================== 远程安装包 ====================

panel_files_ready() {
    [[ -f "$PANEL_DIR/app.py" && -f "$PANEL_DIR/requirements.txt" && -d "$PANEL_DIR/static" ]]
}

clone_panel_from_github() {
    local owner repo tmp clone_dir
    owner=$(github_owner); repo=$(github_repo)
    [[ "${MTP_GITHUB_REPO}" != "YOUR_USERNAME/mtproxy-panel" ]] || return 1
    command -v git &>/dev/null || return 1

    tmp="/tmp/mtproxy-panel-git-$$"
    clone_dir="$tmp/repo"
    print_info "正在从 GitHub 克隆源码: ${MTP_GITHUB_REPO} ..."
    rm -rf "$tmp"
    if ! git clone --depth 1 "https://github.com/${MTP_GITHUB_REPO}.git" "$clone_dir" 2>/dev/null; then
        rm -rf "$tmp"
        return 1
    fi

    [[ -f "$clone_dir/install.sh" && -d "$clone_dir/panel" ]] || { rm -rf "$tmp"; return 1; }
    mkdir -p "$INSTALL_DIR"
    cp -f "$clone_dir/install.sh" "$INSTALL_DIR/"
    cp -a "$clone_dir/panel" "$INSTALL_DIR/"
    chmod +x "$INSTALL_DIR/install.sh"
    rm -rf "$tmp"
    return 0
}

ensure_panel_files() {
    panel_files_ready && return 0

    print_info "未检测到面板程序，正在下载..."
    mkdir -p "$INSTALL_DIR"

    local tmp_tar="/tmp/mtproxy-panel-$$.tar.gz" ok=0
    if curl -fsSL --connect-timeout 15 --max-time 120 \
        "${RELEASE_BASE}/mtproxy-panel.tar.gz" -o "$tmp_tar" 2>/dev/null; then
        tar -xzf "$tmp_tar" -C "$INSTALL_DIR" && ok=1
        rm -f "$tmp_tar"
    fi

    if [[ "$ok" -eq 0 ]] && clone_panel_from_github; then
        ok=1
    fi

    [[ "$ok" -eq 1 ]] || print_error_exit "下载安装包失败。\n请检查网络，或设置: export MTP_GITHUB_REPO=你的用户名/mtproxy-panel"

    chmod +x "$INSTALL_DIR/install.sh" 2>/dev/null || true
    panel_files_ready || print_error_exit "安装包不完整，请联系管理员重新发布"
    print_info "安装包下载完成"
}

# curl | bash 时重新执行本地完整脚本（非交互）
reexec_local_if_needed() {
    [[ -f "$INSTALL_DIR/install.sh" ]] || return 0
    local invoked="${BASH_SOURCE[0]:-}"
    local local_script
    local_script="$(readlink -f "$INSTALL_DIR/install.sh" 2>/dev/null || echo "$INSTALL_DIR/install.sh")"
    [[ "$(readlink -f "$invoked" 2>/dev/null || echo "$invoked")" == "$local_script" ]] && return 0
    stdin_is_piped || [[ "${MTP_NONINTERACTIVE:-}" == "1" ]] || return 0
    export MTP_NONINTERACTIVE=1
    print_info "切换到本地安装脚本: $INSTALL_DIR/install.sh"
    exec bash "$INSTALL_DIR/install.sh" "${@:-install}"
}

make_release() {
    local out_dir="/opt/mtproxy-release"
    mkdir -p "$out_dir"
    print_info "打包发布文件..."
    tar -czf "$out_dir/mtproxy-panel.tar.gz" \
        --exclude='panel/__pycache__' --exclude='panel/**/__pycache__' \
        -C "$INSTALL_DIR" install.sh panel
    cp -f "$INSTALL_DIR/install.sh" "$out_dir/install.sh"
    chmod 644 "$out_dir/mtproxy-panel.tar.gz" "$out_dir/install.sh"
    local size
    size=$(du -h "$out_dir/mtproxy-panel.tar.gz" | cut -f1)
    print_line
    print_info "发布包已生成: $out_dir/mtproxy-panel.tar.gz ($size)"
    echo -e "其他服务器一键安装命令:"
    echo -e "  \033[31m$(install_cmd_hint)\033[0m"
    if [[ "${MTP_GITHUB_REPO}" != "YOUR_USERNAME/mtproxy-panel" ]]; then
        echo -e "GitHub Release: https://github.com/${MTP_GITHUB_REPO}/releases/latest"
    fi
    print_line
}

# ==================== 输出工具 ====================

print_line()  { echo -e "========================================="; }
print_error_exit() {
    print_line; echo -e "[\033[95mERROR\033[0m] $1"; print_line; exit 1
}
print_warning() { echo -e "[\033[33mWARNING\033[0m] $1"; }
print_info()    { echo -e "[\033[32mINFO\033[0m] $1"; }
print_subject() { echo -e "\n\033[32m> $1\033[0m"; }

# ==================== 系统检测 ====================

check_sys() {
    local t=$1 v=$2 rel="" pkg=""
    if [[ -f /etc/redhat-release ]]; then rel=centos; pkg=yum
    elif grep -Eqi "debian|ubuntu|raspbian" /etc/os-release 2>/dev/null; then rel=debian; pkg=apt
    fi
    [[ "$t" == "packageManager" ]] && [[ "$v" == "$pkg" ]]
}

get_ip_public() {
    local ip
    for url in "https://api.ip.sb/ip" "https://ipinfo.io/ip" "https://1.1.1.1/cdn-cgi/trace"; do
        if [[ "$url" == *trace* ]]; then
            ip=$(curl -fsSL --ipv4 --connect-timeout 5 --max-time 8 "$url" 2>/dev/null | grep '^ip=' | cut -d= -f2 || true)
        else
            ip=$(curl -fsSL --ipv4 --connect-timeout 5 --max-time 8 "$url" 2>/dev/null || true)
        fi
        [[ -n "$ip" ]] && echo "$ip" && return
    done
    echo "127.0.0.1"
}

is_port_free() {
    local port=$1
    ! ss -lnt 2>/dev/null | grep -q ":${port} "
}

venv_python() { echo "$INSTALL_DIR/venv/bin/python"; }

is_installed() {
    [[ -f "$INSTALL_DIR/venv/bin/python" ]] && systemctl list-unit-files 2>/dev/null | grep -q "${SERVICE_NAME}.service"
}

# ==================== 依赖安装 ====================

do_install_dep() {
    print_info "安装系统依赖..."
    if check_sys packageManager apt; then
        apt-get update -qq
        apt-get install -y -qq curl wget python3 python3-venv python3-full unzip procps iproute2
    elif check_sys packageManager yum; then
        yum install -y curl wget python3 python3-pip unzip procps-ng iproute
    fi
}

install_python_deps() {
    print_info "安装 Python 依赖..."
    local venv="$INSTALL_DIR/venv"
    python3 -m venv "$venv" 2>/dev/null || { apt-get install -y -qq python3-venv python3-full; python3 -m venv "$venv"; }
    "$venv/bin/pip" install -q --upgrade pip
    "$venv/bin/pip" install -q -r "$PANEL_DIR/requirements.txt"
}

import_legacy_config() {
    local legacy="/home/mtproxy/config"
    [[ -f "$legacy" ]] || return 0
    print_info "检测到旧版 mtproxy 配置，正在迁移..."
    # shellcheck disable=SC1090
    source "$legacy"
    PROXY_PORT=${port:-$PROXY_PORT}
    FAKE_DOMAIN=${domain:-$FAKE_DOMAIN}
    "$(venv_python)" - <<PY
import sys; sys.path.insert(0, "$PANEL_DIR")
import database as db
db.init_db()
db.set_setting("proxy_port", "${port:-34286}")
db.set_setting("stat_port", "${statport:-8888}")
db.set_setting("domain", "${domain:-azure.microsoft.com}")
db.set_setting("adtag", "${adtag:-}")
db.set_setting("fake_tls_mode", "ee")
db.ensure_default_user_from_legacy("${secret:-}", "默认用户（迁移）")
PY
}

write_systemd_service() {
    local port=$1
    cat >"/etc/systemd/system/${SERVICE_NAME}.service" <<EOF
[Unit]
Description=MTProxy Management Panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=${PANEL_DIR}
Environment=MTP_INSTALL_DIR=${INSTALL_DIR}
Environment=MTP_PANEL_DATA=${DATA_DIR}
Environment=MTP_PROXY_DIR=${INSTALL_DIR}/proxy
Environment=MTP_PROXY_LOG=/var/log/mtproxy-panel/proxy.log
ExecStart=${INSTALL_DIR}/venv/bin/python -m uvicorn app:app --host 0.0.0.0 --port ${port}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable "${SERVICE_NAME}.service"
}

# ==================== 交互配置 ====================

stdin_is_piped() {
    [[ -p /dev/stdin ]] \
        || [[ "${BASH_SOURCE[0]:-}" == /dev/fd/* ]] \
        || [[ "${BASH_SOURCE[0]:-}" == /dev/stdin ]]
}

# curl | bash 时 stdin 是脚本内容，必须从终端读取
read_tty() {
    if [[ -r /dev/tty ]]; then
        read "$@" </dev/tty || true
    else
        read "$@" || true
    fi
}

pick_free_port() {
    local port=$1 min=$2 max=$3
    local try=0
    while [ "$try" -lt 50 ]; do
        is_port_free "$port" && { echo "$port"; return; }
        port=$((port + 1))
        [ "$port" -gt "$max" ] && port=$min
        try=$((try + 1))
    done
    echo "$1"
}

check_fake_domain() {
    local domain=$1
    local http_code
    http_code=$(curl -I -m 10 -o /dev/null -s -w "%{http_code}" "https://${domain}" 2>/dev/null || echo "000")
    # Fake-TLS 只需 HTTPS 可达；404/403 等页面状态完全正常
    [[ "$http_code" != "000" && "$http_code" =~ ^[0-9]{3}$ ]] && return 0
    if command -v openssl &>/dev/null; then
        echo | timeout 8 openssl s_client -connect "${domain}:443" -servername "$domain" </dev/null 2>/dev/null \
            | grep -qE 'CONNECTED|Protocol' && return 0
    fi
    return 1
}

pick_fake_domain() {
    local preferred=${1:-}
    [[ -n "$preferred" ]] && check_fake_domain "$preferred" && { echo "$preferred"; return; }
    local d
    for d in "${FAKE_DOMAIN_CANDIDATES[@]}"; do
        check_fake_domain "$d" && { echo "$d"; return; }
    done
    echo "${preferred:-www.google.com}"
}

do_default_config() {
    PANEL_PORT=${MTP_PANEL_PORT:-$PANEL_PORT}
    PROXY_PORT=${MTP_PROXY_PORT:-$PROXY_PORT}
    FAKE_TLS_MODE=${MTP_FAKE_TLS_MODE:-$FAKE_TLS_MODE}

    is_port_free "$PANEL_PORT" || PANEL_PORT=$(pick_free_port "$PANEL_PORT" 1024 65535)
    is_port_free "$PROXY_PORT" || PROXY_PORT=$(pick_free_port "$PROXY_PORT" 1 65535)

    FAKE_DOMAIN=$(pick_fake_domain "${MTP_FAKE_DOMAIN:-$FAKE_DOMAIN}")
    print_info "使用默认配置（可在面板中修改）:"
    print_info "  面板端口: ${PANEL_PORT}  代理端口: ${PROXY_PORT}"
    print_info "  伪装域名: ${FAKE_DOMAIN}  混淆模式: ${FAKE_TLS_MODE}"
}

prompt_port() {
    local name=$1 default=$2 min=$3 max=$4
    while true; do
        print_subject "请输入${name} [${min}-${max}]"
        local input=""
        read_tty -p "(默认: ${default}):" input
        input=${input:-$default}
        if [[ "$input" =~ ^[0-9]+$ ]] && [ "$input" -ge "$min" ] && [ "$input" -le "$max" ]; then
            if is_port_free "$input"; then
                echo "$input"; return
            fi
            print_warning "端口 ${input} 已被占用，请换一个"
        else
            print_warning "端口无效，请重新输入"
        fi
    done
}

do_interactive_config() {
    if [[ "${MTP_NONINTERACTIVE:-}" == "1" ]] || stdin_is_piped; then
        do_default_config
        return
    fi

    PANEL_PORT=$(prompt_port "面板访问端口" "$PANEL_PORT" 1024 65535)
    PROXY_PORT=$(prompt_port "MTProxy 代理端口" "$PROXY_PORT" 1 65535)

    FAKE_DOMAIN=$(pick_fake_domain "$FAKE_DOMAIN")
    while true; do
        print_subject "请输入伪装域名（Fake-TLS 用，404 页面也可用）"
        local input="" force=""
        read_tty -p "(默认: ${FAKE_DOMAIN}):" input
        input=${input:-$FAKE_DOMAIN}
        if check_fake_domain "$input"; then
            FAKE_DOMAIN=$input; break
        fi
        print_warning "域名 https://${input} HTTPS 检测失败"
        read_tty -p "仍要使用 ${input}？(y/N):" force
        if [[ "$(echo "$force" | tr '[:upper:]' '[:lower:]')" == "y" ]]; then
            FAKE_DOMAIN=$input; break
        fi
        print_info "将自动尝试其他常用域名..."
        FAKE_DOMAIN=$(pick_fake_domain "")
        print_info "已切换为: ${FAKE_DOMAIN}"
    done

    print_subject "选择 Fake-TLS 混淆模式"
    echo -e "  \033[36m1.\033[0m ee — 标准 Fake-TLS（域名混淆，推荐）"
    echo -e "  \033[36m2.\033[0m dd — 随机填充 Fake-TLS"
    echo -e "  \033[36m3.\033[0m 关闭 — 经典模式（无混淆）"
    local tls_choice=""
    read_tty -p "(默认: 1):" tls_choice
    case "${tls_choice:-1}" in
        2) FAKE_TLS_MODE="dd" ;;
        3) FAKE_TLS_MODE="off" ;;
        *) FAKE_TLS_MODE="ee" ;;
    esac
}

init_settings() {
    "$(venv_python)" - <<PY
import sys; sys.path.insert(0, "$PANEL_DIR")
import database as db
db.init_db()
db.set_setting("panel_port", "$PANEL_PORT")
if not db.get_setting("proxy_port"): db.set_setting("proxy_port", "$PROXY_PORT")
db.set_setting("domain", "$FAKE_DOMAIN")
db.set_setting("fake_tls_mode", "$FAKE_TLS_MODE")
if not db.get_setting("public_ip"): db.set_setting("public_ip", "$PUBLIC_IP")
if not db.list_users(): db.create_user("默认用户", 0, None)
PY
}

# ==================== 服务控制 ====================

start_panel() {
    systemctl start "${SERVICE_NAME}.service" 2>/dev/null || systemctl restart "${SERVICE_NAME}.service"
}

stop_panel() {
    systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
}

start_proxy() {
    "$(venv_python)" - <<'PY'
import sys; sys.path.insert(0, "/opt/mtproxy-panel/panel")
from mtproxy_service import start_proxy
ok = start_proxy()
print("ok" if ok else "fail")
PY
}

stop_proxy() {
    "$(venv_python)" - <<'PY'
import sys; sys.path.insert(0, "/opt/mtproxy-panel/panel")
from mtproxy_service import stop_proxy
stop_proxy()
PY
}

# ==================== 信息展示 ====================

info_panel() {
    "$(venv_python)" - <<'PY'
import sys; sys.path.insert(0, "/opt/mtproxy-panel/panel")
from database import get_all_settings, list_users
from mtproxy_service import is_proxy_running, get_public_ip, count_connections, build_client_secret, build_proxy_link

s = get_all_settings()
ip = s.get("public_ip") or get_public_ip()
port = int(s.get("proxy_port", 443))
panel_port = s.get("panel_port", "8088")
running = is_proxy_running()
mode = s.get("fake_tls_mode", "ee")
domain = s.get("domain", "")
users = list_users()
active = sum(1 for u in users if u["enabled"])

status = "\033[32m运行中\033[0m" if running else "\033[33m已停止\033[0m"
print(f"MTProxy 管理面板: {status}")
print(f"面板地址: \033[31mhttp://{ip}:{panel_port}\033[0m")
print(f"代理端口: \033[31m{port}\033[0m  在线连接: {count_connections(port)}")
print(f"混淆模式: {mode}  伪装域名: {domain}")
print(f"用户数量: {len(users)} (活跃 {active})")
print(f"默认账号: \033[33madmin / admin123\033[0m")

for u in users:
    if not u["enabled"]: continue
    cs = build_client_secret(u["secret"], domain, mode)
    tg, _ = build_proxy_link(ip, port, cs)
    label = u["remark"] or f"用户{u['id']}"
    print(f"  [{label}] {tg}")
PY
}

setup_nginx_proxy() {
    command -v nginx &>/dev/null || return 0
    local flux_conf="/etc/nginx/sites-available/flux"
    [[ -f "$flux_conf" ]] || return 0
    if grep -q "location /mtproxy/" "$flux_conf" 2>/dev/null; then
        print_info "Nginx 反代已存在，跳过"
        return 0
    fi
    print_info "配置 Nginx HTTPS 反代 (/mtproxy/)..."
    # 在第一个 location / 之前插入反代块
    sed -i '/location \/ {/i\
    location = /mtproxy {\
        return 301 https://$host/mtproxy/;\
    }\
    location /mtproxy/ {\
        proxy_pass http://127.0.0.1:'"${PANEL_PORT}"'/;\
        proxy_set_header Host $host;\
        proxy_set_header X-Real-IP $remote_addr;\
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\
        proxy_set_header X-Forwarded-Proto $scheme;\
        proxy_http_version 1.1;\
        proxy_set_header Upgrade $http_upgrade;\
        proxy_set_header Connection "upgrade";\
        proxy_read_timeout 300s;\
    }\
' "$flux_conf"
    nginx -t && systemctl reload nginx
    print_info "Nginx 反代配置完成"
}

open_firewall_ports() {
    print_info "配置防火墙规则..."
    for port in "$PANEL_PORT" "$PROXY_PORT"; do
        iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null \
            || iptables -I INPUT -p tcp --dport "$port" -j ACCEPT
    done
    if command -v netfilter-persistent &>/dev/null; then
        netfilter-persistent save 2>/dev/null || true
    elif [[ -d /etc/iptables ]]; then
        iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
    fi
}

show_result() {
    print_line
    echo -e "\033[32m🎉 MTProxy 管理面板安装完成\033[0m"
    print_line
    info_panel
    if grep -q "location /mtproxy/" /etc/nginx/sites-available/flux 2>/dev/null; then
        echo -e "HTTPS 访问：\033[31mhttps://Hkt.237700.xyz/mtproxy/\033[0m （推荐，走443端口）"
    fi
    print_line
    echo -e "功能概览:"
    echo -e "  ① 多用户密钥管理（添加/删除/禁用/备注）"
    echo -e "  ② 流量配额 + 到期自动失效 + 实时统计"
    echo -e "  ③ Fake-TLS 混淆 (ee/dd/关闭) + 自定义伪装域名"
    echo -e "  ④ 一键复制 tg:// 链接 + 二维码扫码"
    echo -e "  ⑤ 修改管理员/面板端口 + CPU/内存/硬盘监控"
    print_line
    echo "管理命令:"
    echo -e "\t启动全部\t bash $SCRIPT_PATH start"
    echo -e "\t停止全部\t bash $SCRIPT_PATH stop"
    echo -e "\t重启全部\t bash $SCRIPT_PATH restart"
    echo -e "\t查看状态\t bash $SCRIPT_PATH status"
    echo -e "\t重置数据\t bash $SCRIPT_PATH reset"
    echo -e "\t重装面板\t bash $SCRIPT_PATH reinstall"
    echo -e "\t卸载面板\t bash $SCRIPT_PATH uninstall"
    echo -e "\t一键安装\t $(install_cmd_hint)"
    print_line
    echo -e "⚠️  登录后请立即修改默认密码！"
}

# ==================== 主流程 ====================

do_install() {
    ensure_panel_files
    stdin_is_piped && export MTP_NONINTERACTIVE=1
    PUBLIC_IP=$(get_ip_public)
    print_line
    echo "MTProxy 管理面板 · 一键安装 v2.0"
    print_line

    do_interactive_config
    do_install_dep
    install_python_deps
    mkdir -p "$DATA_DIR" /var/log/mtproxy-panel "${INSTALL_DIR}/proxy/bin" "${INSTALL_DIR}/proxy/pid"

    import_legacy_config
    init_settings
    write_systemd_service "$PANEL_PORT"
    open_firewall_ports
    setup_nginx_proxy

    print_info "启动管理面板..."
    start_panel; sleep 2

    print_info "启动 MTProxy 代理..."
    if [[ "$(start_proxy)" != "ok" ]]; then
        print_warning "代理启动失败，请检查端口 ${PROXY_PORT} 是否被占用"
    fi

    show_result
}

do_reset() {
    local c=""; read_tty -p "确认重置？将清空所有用户数据，保留代理配置，管理员恢复为 admin/admin123 (y/N): " c
    [[ "$c" == "y" || "$c" == "Y" ]] || exit 0

    print_info "停止服务..."
    stop_proxy; stop_panel

    print_info "备份并重建数据库..."
    [[ -f "$DATA_DIR/panel.db" ]] && cp "$DATA_DIR/panel.db" "$DATA_DIR/panel.db.bak.$(date +%s)"

    "$(venv_python)" - <<'PY'
import sys; sys.path.insert(0, "/opt/mtproxy-panel/panel")
import os, database as db

# 保留代理相关配置
keep = {}
for k in ("proxy_port", "panel_port", "domain", "fake_tls_mode", "adtag", "public_ip", "stat_port"):
    keep[k] = db.get_setting(k)

db_path = db.DB_PATH
if os.path.exists(db_path):
    os.remove(db_path)

db.init_db()
for k, v in keep.items():
    if v: db.set_setting(k, v)
db.create_user("默认用户", 0, None)
print("重置完成")
PY

    print_info "重启服务..."
    start_panel; sleep 2; start_proxy

    print_line
    print_info "面板已重置，管理员账号: admin / admin123"
    info_panel
}

do_uninstall() {
    local c=""; read_tty -p "确认卸载 MTProxy 管理面板？(y/N): " c
    [[ "$c" == "y" || "$c" == "Y" ]] || exit 0
    stop_panel
    stop_proxy
    systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
    rm -f "/etc/systemd/system/${SERVICE_NAME}.service"
    systemctl daemon-reload
    local d=""; read_tty -p "是否删除数据目录 ${INSTALL_DIR}？(y/N): " d
    [[ "$d" == "y" || "$d" == "Y" ]] && rm -rf "$INSTALL_DIR" /var/log/mtproxy-panel
    print_info "卸载完成"
}

do_status() {
    systemctl status "${SERVICE_NAME}.service" --no-pager 2>/dev/null | head -5 || print_warning "面板服务未运行"
    print_line
    info_panel
}

# ==================== 入口 ====================

# curl | bash 无参数时默认 install；本机直接执行无参数时显示状态/帮助
if [[ -p "${BASH_SOURCE[0]:-}" || "${BASH_SOURCE[0]:-}" == /dev/fd/* || "${BASH_SOURCE[0]:-}" == /dev/stdin ]]; then
    param=${1:-install}
else
    param=${1:-}
fi

reexec_local_if_needed "${param:-install}"
ensure_panel_files 2>/dev/null || true

# 下载完安装包后，管道安装一律走本地脚本 + 非交互
if [[ -f "$INSTALL_DIR/install.sh" ]] && { stdin_is_piped || [[ "${MTP_NONINTERACTIVE:-}" == "1" ]]; }; then
    case "${param:-install}" in
        install|reinstall)
            export MTP_NONINTERACTIVE=1
            exec bash "$INSTALL_DIR/install.sh" "${param:-install}"
            ;;
    esac
fi

case "$param" in
    start)
        print_info "启动面板 + 代理"
        start_panel; start_proxy
        info_panel
        ;;
    stop)
        print_info "停止面板 + 代理"
        stop_proxy; stop_panel
        print_info "已停止"
        ;;
    restart)
        print_info "重启面板 + 代理"
        stop_proxy; start_proxy
        systemctl restart "${SERVICE_NAME}.service"
        sleep 2; info_panel
        ;;
    status)    do_status ;;
    install)   do_install ;;
    reinstall) do_install ;;
    uninstall) do_uninstall ;;
    reset)     do_reset ;;
    release|make-release) make_release ;;
    "")
        if is_installed; then
            echo "MTProxy 管理面板 · 一键管理脚本 v2.0"
            print_line
            info_panel
            print_line
            echo "使用方式:"
            echo -e "\t启动全部\t bash $SCRIPT_PATH start"
            echo -e "\t停止全部\t bash $SCRIPT_PATH stop"
            echo -e "\t重启全部\t bash $SCRIPT_PATH restart"
            echo -e "\t查看状态\t bash $SCRIPT_PATH status"
            echo -e "\t重装面板\t bash $SCRIPT_PATH reinstall"
            echo -e "\t卸载面板\t bash $SCRIPT_PATH uninstall"
        else
            do_install
        fi
        ;;
    *) print_error_exit "未知参数: $param（支持 start/stop/restart/status/reset/install/reinstall/uninstall/release）" ;;
esac