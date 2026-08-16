#!/bin/bash
# Wiki 层周度审计（T4）：发现 frontmatter 问题/重复/悬空链接/新鲜度/未闭环待核实
# 由 obsidian-server-audit.timer 每周触发，结果追加到日志
set -euo pipefail
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
SCRIPT="$HOME/.hermes/scripts/wiki_audit.py"
LOG="$HOME/.hermes/logs/wiki-audit.log"

echo "=== wiki-audit $(date +%F_%T) ===" >> "$LOG"
python3 "$SCRIPT" --vault "$VAULT" >> "$LOG" 2>&1
echo >> "$LOG"
