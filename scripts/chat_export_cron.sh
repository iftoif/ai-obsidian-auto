#!/usr/bin/env bash
# Hermes 微信/Telegram 日志导出（每小时 :00）
# 依赖：Hermes Gateway 已配置（见 docs/deployment.md）
set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOG="$HERMES_HOME/logs/chat_export.log"
mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== chat_export $(date +%F_%T) ==="

CHAT_EXPORT="$HERMES_HOME/scripts/chat_export.py"
if [ -f "$CHAT_EXPORT" ]; then
  if python3 "$CHAT_EXPORT" 2>&1 | tail -3; then
    echo "✅ Hermes 日志导出完成"
  else
    echo "❌ Hermes 日志导出失败" >&2
    exit 1
  fi
else
  echo "⚠️ 未找到 chat_export.py（未装 Hermes Gateway 则忽略）"
fi
