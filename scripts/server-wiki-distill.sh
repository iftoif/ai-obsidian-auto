#!/usr/bin/env bash
# 蒸馏 service 入口：设置环境变量后调用统一蒸馏脚本
# 环境变量优先（setup-server 注入），回退到默认值
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
export HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
export AI_DISTILL_PROVIDER="${AI_DISTILL_PROVIDER:-openai-codex}"
export AI_DISTILL_MODEL="${AI_DISTILL_MODEL:-gpt-5.6-luna}"
exec "$SCRIPT_DIR/ai_chat_unified_distill_cron.sh" "$@"   # 同目录互调
