#!/usr/bin/env bash
# Claude/Pi/DSH 会话导出（每小时 :03）
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
LOG="$HERMES_HOME/logs/ai_chat_export.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== ai_chat_export $(date +%F_%T) ==="

AI_EXPORT="$SCRIPT_DIR/ai_chat_export.py"   # 同目录互调，git pull 更新立即生效
if [ -f "$AI_EXPORT" ]; then
  if python3 "$AI_EXPORT" --tool all 2>&1 | tail -3; then
    echo "✅ AI 会话导出完成"
  else
    echo "❌ AI 会话导出失败" >&2
    exit 1
  fi
else
  echo "⚠️ 未找到 ai_chat_export.py"
fi
