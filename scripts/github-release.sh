#!/bin/bash
# ============================================================
# 一键发布 GitHub Release（含 install.sh + 安装包）
# 用法: export GITHUB_TOKEN=ghp_xxx && bash github-release.sh v1.0.1
# ============================================================

set -euo pipefail

REPO="zxcvdyq888-create/mtproxy-panel"
TAG="${1:-v1.0.1}"
PROJECT_DIR="/root/mtproxy-panel"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "[ERROR] 请先设置 Token:"
    echo "  export GITHUB_TOKEN=ghp_你的Token"
    exit 1
fi

cd "$PROJECT_DIR"

echo "[INFO] 打包安装文件..."
mkdir -p /tmp/mtproxy-release-build
tar -czf /tmp/mtproxy-release-build/mtproxy-panel.tar.gz \
    --exclude='panel/__pycache__' \
    -C "$PROJECT_DIR" install.sh panel
cp -f "$PROJECT_DIR/install.sh" /tmp/mtproxy-release-build/install.sh

echo "[INFO] 创建 GitHub Release: ${TAG}"
RELEASE_JSON=$(curl -sS -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Accept: application/vnd.github+json" \
    "https://api.github.com/repos/${REPO}/releases" \
    -d "{\"tag_name\":\"${TAG}\",\"name\":\"MTProxy Panel ${TAG}\",\"body\":\"一键安装 MTProxy 管理面板\",\"draft\":false,\"prerelease\":false}")

UPLOAD_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if 'upload_url' in d:
    print(d['upload_url'].split('{')[0])
elif 'message' in d:
    print('ERROR:' + d['message'])
")

if [[ "$UPLOAD_URL" == ERROR:* ]]; then
    echo "[WARN] 创建 Release 失败: ${UPLOAD_URL#ERROR:}"
    echo "[INFO] 尝试获取已有 Release..."
    UPLOAD_URL=$(curl -sS -H "Authorization: token ${GITHUB_TOKEN}" \
        "https://api.github.com/repos/${REPO}/releases/tags/${TAG}" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('upload_url','').split('{')[0])")
fi

[[ -n "$UPLOAD_URL" ]] || { echo "[ERROR] 无法获取 upload_url"; exit 1; }

echo "[INFO] 上传 install.sh ..."
curl -sS -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @/tmp/mtproxy-release-build/install.sh \
    "${UPLOAD_URL}?name=install.sh" > /dev/null

echo "[INFO] 上传 mtproxy-panel.tar.gz ..."
curl -sS -X POST \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Content-Type: application/octet-stream" \
    --data-binary @/tmp/mtproxy-release-build/mtproxy-panel.tar.gz \
    "${UPLOAD_URL}?name=mtproxy-panel.tar.gz" > /dev/null

rm -rf /tmp/mtproxy-release-build

echo "========================================="
echo "[OK] Release 发布完成!"
echo "页面: https://github.com/${REPO}/releases/tag/${TAG}"
echo "安装: curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash"
echo "========================================="