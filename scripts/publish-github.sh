#!/bin/bash
# ============================================================
# 推送 MTProxy 管理面板到 GitHub
# 用法: GITHUB_TOKEN=ghp_xxx bash scripts/publish-github.sh
# ============================================================
set -euo pipefail

REPO="zxcvdyq888-create/mtproxy-panel"
BRANCH="${BRANCH:-main}"
# 项目目录 = 脚本所在目录的父目录，不再硬编码 /root/mtproxy-panel
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "[ERROR] 请先设置 Token: GITHUB_TOKEN=ghp_xxx bash scripts/publish-github.sh"
    exit 1
fi

cd "$PROJECT_DIR"

echo "[INFO] 项目目录: $PROJECT_DIR"
echo "[INFO] Git 状态:"
git status --short

echo "[INFO] 推送到 GitHub: ${REPO} (${BRANCH})"
git push "https://x-access-token:${GITHUB_TOKEN}@github.com/${REPO}.git" "$BRANCH"

git remote set-url origin "https://github.com/${REPO}.git" 2>/dev/null || \
    git remote add origin "https://github.com/${REPO}.git"

echo "========================================="
echo "[OK] 推送完成!"
echo "仓库: https://github.com/${REPO}"
echo "安装: curl -fsSL https://raw.githubusercontent.com/${REPO}/${BRANCH}/install.sh | bash"
echo "========================================="
