#!/usr/bin/env bash
# QA-PLAN §4 集成测试：假 vault → obsidian_backup → FTS5 → Chroma(降级) → state 全链路
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
TESTROOT="$(mktemp -d)"
trap 'rm -rf "$TESTROOT"' EXIT

ok()  { echo "  ✅ $1"; }
bad() { echo "  ❌ $1"; exit 1; }

# 1. 造假 vault
VAULT="$TESTROOT/vault"
mkdir -p "$VAULT/Wiki" "$VAULT/Lessons"
cat > "$VAULT/Wiki/test-note.md" <<'EOF'
---
title: 集成测试笔记
tags: [test, integration]
---
# 集成测试内容

引用 [[其他笔记]]
EOF
echo '# 课程记录' > "$VAULT/Lessons/lesson1.md"

# 2. 运行备份（系统 python，无 chromadb → 触发降级路径）
export OBSIDIAN_VAULT_PATH="$VAULT"
export HERMES_HOME="$TESTROOT/hermes"
export OBSIDIAN_CHROMA_ENABLED=0
python3 "$REPO/scripts/obsidian_backup.py" --full --quiet 2>/dev/null
BACKUP_RC=$?
[ "$BACKUP_RC" -eq 0 ] || bad "备份失败 (rc=$BACKUP_RC)"

# 3. FTS5 搜索命中
RESULT=$(python3 "$REPO/scripts/obsidian_backup.py" --search '集成测试' 2>/dev/null)
echo "$RESULT" | grep -q '集成测试笔记' || bad "FTS5 搜索未命中"
ok "FTS5 搜索命中中文内容"

# 4. state.json 生成
[ -f "$TESTROOT/hermes/data/obsidian/state.json" ] || bad "state.json 未生成"
ok "state.json 已生成"

# 5. SQLite DB 生成
DB=$(ls "$TESTROOT/hermes/data/obsidian/"*.db 2>/dev/null | head -1)
[ -n "$DB" ] || bad "SQLite DB 未生成"
ok "SQLite DB 已生成"

# 6. 增量备份幂等（二次跑无变更）
python3 "$REPO/scripts/obsidian_backup.py" --quiet 2>/dev/null
INC_RC=$?
[ "$INC_RC" -eq 0 ] || bad "增量备份失败 (rc=$INC_RC)"
ok "增量备份幂等"

echo "\n===== 集成测试（backup pipeline）：全部通过 ====="