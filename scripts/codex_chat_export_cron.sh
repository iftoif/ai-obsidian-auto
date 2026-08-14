#!/usr/bin/env bash
# Codex 会话导出（每小时 :07）
set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
LOG="$HERMES_HOME/logs/codex_chat_export.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== codex_export $(date +%F_%T) ==="

CODEX_EXPORT="$OBSIDIAN_VAULT_PATH/Codex/tools/export_codex_chat_logs.py"
if [ -f "$CODEX_EXPORT" ]; then
  python3 "$CODEX_EXPORT" --vault "$OBSIDIAN_VAULT_PATH" --codex-home "$HOME/.codex" 2>&1 | tail -2
  echo "✅ Codex 导出完成"
else
  echo "⚠️ 未找到 export_codex_chat_logs.py"
fi
