# 维护者指南

本文档面向仓库维护者，普通用户请看 [README.md](../README.md)。

## 推送代码到 GitHub

```bash
GITHUB_TOKEN=ghp_xxx bash scripts/publish-github.sh
```

脚本会自动以 `scripts/` 所在目录的父目录为项目根目录推送到 `main` 分支。

## 发布 Release

```bash
GITHUB_TOKEN=ghp_xxx bash scripts/github-release.sh v2.1.0
```

会创建 GitHub Release 并上传 `install.sh` 与 `mtproxy-panel.tar.gz` 安装包。

## 版本号规范

- `CHANGELOG.md` 记录每个版本的安全修复、功能变更与破坏性变更
- 发版前更新 `README.md` 顶部的版本徽标与发布日期
