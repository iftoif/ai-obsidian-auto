#!/usr/bin/env bash
# Claude/Pi/DSH 会话导出（每小时 :03）
set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
LOG="$HERMES_HOME/logs/ai_chat_export.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== ai_chat_export $(date +%F_%T) ==="

AI_EXPORT="$HERMES_HOME/scripts/ai_chat_export.py"
if [ -f "$AI_EXPORT" ]; then
  python3 "$AI_EXPORT" --tool all 2>&1 | tail -3
  echo "✅ AI 会话导出完成"
else
  echo "⚠️ 未找到 ai_chat_export.py"
fi
