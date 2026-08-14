#!/bin/bash
# Obsidian 增量索引 (SQLite FTS5 + 可选 ChromaDB)
# 被 systemd timer 调用（setup-server 注入 OBSIDIAN_VAULT_PATH / HERMES_HOME）
set -euo pipefail

export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PYBIN="$HERMES_HOME/obsidian-backup-env/bin/python3"
SCRIPT="$HERMES_HOME/scripts/obsidian_backup.py"

OUTPUT=$(OBSIDIAN_CHROMA_ENABLED=0 "$PYBIN" "$SCRIPT" --quiet 2>&1)
EXIT=$?

if [ $EXIT -ne 0 ]; then
  echo "❌ Obsidian 备份失败 (exit=$EXIT)"
  echo "$OUTPUT" | tail -10
elif echo "$OUTPUT" | grep -q "无变更"; then
  # 无变更时静默
  exit 0
else
  echo "📦 Obsidian 增量备份完成"
  echo "$OUTPUT" | grep -E "新增|删除|处理|完成|记录" | head -5 || true
fi
