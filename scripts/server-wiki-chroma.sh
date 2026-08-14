#!/usr/bin/env bash
# Chroma 语义索引重建 service 入口（调用统一索引脚本 --full）
set -Eeuo pipefail


# 配置兜底：优先环境变量（systemd 注入），回退 source 仓库 .env（手工部署路径）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$REPO_DIR/.env" ]; then
  set -a; . "$REPO_DIR/.env"; set +a
fi
export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
exec "$HERMES_HOME/obsidian-backup-env/bin/python" "$SCRIPT_DIR/obsidian_backup.py" --full --quiet   # 同目录互调
