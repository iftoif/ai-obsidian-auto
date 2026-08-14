#!/bin/bash
# Weekly high-signal ChromaDB rebuild for the Obsidian LLM Wiki.
# 复用 obsidian_backup.py 的 --full 模式（SQLite 全量 + Chroma 语义索引重建）
set -euo pipefail

export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
PYBIN="$HERMES_HOME/obsidian-backup-env/bin/python3"
SCRIPT="$HERMES_HOME/scripts/obsidian_backup.py"

OUTPUT=$(OBSIDIAN_CHROMA_ENABLED=1 "$PYBIN" "$SCRIPT" --full --quiet 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
  echo "❌ Wiki Chroma 重建失败 (exit=$RC)"
  echo "$OUTPUT" | tail -20
  exit $RC
fi

echo "$OUTPUT" | tail -5
