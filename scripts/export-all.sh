#!/usr/bin/env bash
# 导出所有已拉取的会话（Claude/Pi/DSH + Codex）
# 由 crontab 每小时调度；统一从 .env 读配置
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 加载配置（.env 是唯一配置源）
if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
else
  echo "❌ 请先复制 .env.example 为 .env 并填写你的配置"
  exit 1
fi

export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

FAILED=0

# Claude/Pi/DSH 导出（统一导出器）
AI_EXPORT="$HERMES_HOME/scripts/ai_chat_export.py"
if [ -f "$AI_EXPORT" ]; then
  if python3 "$AI_EXPORT" --tool all 2>&1 | tail -3; then
    echo "✅ Claude/Pi/DSH 导出完成"
  else
    echo "❌ Claude/Pi/DSH 导出失败" >&2
    FAILED=1
  fi
else
  echo "⚠️ 未找到 ai_chat_export.py（$AI_EXPORT），请确认 HERMES_HOME 配置"
fi

# Codex 导出
CODEX_EXPORT="$OBSIDIAN_VAULT_PATH/Codex/tools/export_codex_chat_logs.py"
if [ -f "$CODEX_EXPORT" ]; then
  if python3 "$CODEX_EXPORT" --vault "$OBSIDIAN_VAULT_PATH" --codex-home "$HOME/.codex" 2>&1 | tail -2; then
    echo "✅ Codex 导出完成"
  else
    echo "❌ Codex 导出失败" >&2
    FAILED=1
  fi
else
  echo "⚠️ 未找到 export_codex_chat_logs.py（$CODEX_EXPORT）"
fi

[ "$FAILED" -eq 0 ] || { echo "❌ 导出有失败，本轮异常退出" >&2; exit 1; }
