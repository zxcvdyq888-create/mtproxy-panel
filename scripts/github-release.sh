#!/bin/bash
# ============================================================
# 发布 GitHub Release（含 install.sh + 安装包）
# 用法: GITHUB_TOKEN=ghp_xxx bash scripts/github-release.sh v2.1.0
# ============================================================
set -euo pipefail

REPO="zxcvdyq888-create/mtproxy-panel"
TAG="${1:-v2.1.0}"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${GITHUB_TOKEN:-}" ]]; then
    echo "[ERROR] 请先设置 Token: GITHUB_TOKEN=ghp_xxx bash scripts/github-release.sh v2.1.0"
    exit 1
fi

cd "$PROJECT_DIR"

echo "[INFO] 打包安装文件..."
BUILD_DIR="$(mktemp -d)"
tar -czf "$BUILD_DIR/mtproxy-panel.tar.gz" \
    --exclude='panel/__pycache__' \
    -C "$PROJECT_DIR" install.sh panel
cp -f "$PROJECT_DIR/install.sh" "$BUILD_DIR/install.sh"

AUTH_HEADER="Authorization: Bearer ${GITHUB_TOKEN}"
echo "[INFO] 创建 GitHub Release: ${TAG}"
RELEASE_JSON=$(curl -sS -X POST \
    -H "$AUTH_HEADER" \
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
    UPLOAD_URL=$(curl -sS -H "$AUTH_HEADER" \
        "https://api.github.com/repos/${REPO}/releases/tags/${TAG}" | \
        python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('upload_url','').split('{')[0])")
fi

[[ -n "$UPLOAD_URL" ]] || { echo "[ERROR] 无法获取 upload_url"; rm -rf "$BUILD_DIR"; exit 1; }

for f in install.sh mtproxy-panel.tar.gz; do
    echo "[INFO] 上传 $f ..."
    curl -sS -X POST \
        -H "$AUTH_HEADER" \
        -H "Content-Type: application/octet-stream" \
        --data-binary "@$BUILD_DIR/$f" \
        "${UPLOAD_URL}?name=$f" > /dev/null
done

rm -rf "$BUILD_DIR"

echo "========================================="
echo "[OK] Release 发布完成!"
echo "页面: https://github.com/${REPO}/releases/tag/${TAG}"
echo "安装: curl -fsSL https://raw.githubusercontent.com/${REPO}/main/install.sh | bash"
echo "========================================="
