#!/bin/bash
# ============================================================
# 一键推送 MTProxy 管理面板到 GitHub
# 用法: export GITHUB_TOKEN=ghp_xxx && bash publish-github.sh
# ============================================================

set -euo pipefail

REPO="zxcvdyq888-create/mtproxy-panel"
BRANCH="main"
PROJECT_DIR="/root/mtproxy-panel"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "[ERROR] 请先设置 Token:"
    echo "  export GITHUB_TOKEN=ghp_你的Token"
    exit 1
fi

cd "$PROJECT_DIR"

echo "[INFO] 检查 Git 状态..."
git status --short

echo "[INFO] 推送到 GitHub: ${REPO} (${BRANCH})"
git push "https://${REPO%%/*}:${GITHUB_TOKEN}@github.com/${REPO}.git" "$BRANCH"

git remote set-url origin "https://github.com/${REPO}.git" 2>/dev/null || \
    git remote add origin "https://github.com/${REPO}.git"

echo "[INFO] 同步到官方发布地址..."
cp -f "$PROJECT_DIR/install.sh" /opt/mtproxy-panel/install.sh 2>/dev/null || true
bash /opt/mtproxy-panel/install.sh release 2>/dev/null || true

echo "========================================="
echo "[OK] 推送完成!"
echo "仓库: https://github.com/${REPO}"
echo "安装: curl -fsSL https://raw.githubusercontent.com/${REPO}/${BRANCH}/install.sh | bash"
echo "========================================="