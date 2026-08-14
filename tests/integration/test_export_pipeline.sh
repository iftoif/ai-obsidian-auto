#!/usr/bin/env bash
# 集成测试：export 管道（假 Claude jsonl → Raw md）
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTROOT="$(mktemp -d /tmp/qa-export.XXXXXX)"
PASS=0; FAIL=0
trap 'rm -rf "$TESTROOT"' EXIT
ok(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
bad(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }

# 造假 Claude 会话
mkdir -p "$TESTROOT/home/.claude/projects/p1"
cat > "$TESTROOT/home/.claude/projects/p1/s1.jsonl" <<'EOF'
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"第一条用户消息"}]},"timestamp":"2026-08-15T10:00:00Z","sessionId":"s1"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"第一条助手回复"}]},"timestamp":"2026-08-15T10:00:01Z","sessionId":"s1"}
EOF

echo "▸ export 管道"

# 1. 导出（HOME 指向假 home，vault 指向测试 vault）
mkdir -p "$TESTROOT/vault"
if HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" HERMES_HOME="$TESTROOT/home/.hermes" python3 "$REPO/scripts/ai_chat_export.py" --tool Claude 2>&1 | tail -2; then
  ok "导出命令执行"
else
  bad "导出命令失败"
fi

# 2. Raw md 生成
if ls "$TESTROOT/vault/Claude/Chat Logs/2026/"*.md >/dev/null 2>&1; then
  ok "Raw Chat Log 生成"
else
  bad "Raw Chat Log 未生成"; find "$TESTROOT/vault" -type f | head -5
fi

# 3. 内容含两条消息
MD=$(ls "$TESTROOT/vault/Claude/Chat Logs/2026/"*.md | head -1)
if grep -q "第一条用户消息" "$MD" && grep -q "第一条助手回复" "$MD"; then
  ok "两条消息都导出"
else
  bad "消息缺失"; cat "$MD"
fi

# 4. 幂等：再次导出无新增（seen 去重）
BEFORE=$(wc -l < "$MD")
HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" HERMES_HOME="$TESTROOT/home/.hermes" python3 "$REPO/scripts/ai_chat_export.py" --tool Claude >/dev/null 2>&1
AFTER=$(wc -l < "$MD")
if [ "$BEFORE" -eq "$AFTER" ]; then
  ok "幂等（无重复导出）"
else
  bad "非幂等: $BEFORE → $AFTER"
fi

# 5. 两条相同消息 → 都导出（R12 修复：event_hash 含 line_no）
cat > "$TESTROOT/home/.claude/projects/p1/s2.jsonl" <<'EOF'
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"重复的消息"}]},"timestamp":"2026-08-15T11:00:00Z","sessionId":"s2"}
{"type":"user","message":{"role":"user","content":[{"type":"text","text":"重复的消息"}]},"timestamp":"2026-08-15T11:00:01Z","sessionId":"s2"}
EOF
HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" HERMES_HOME="$TESTROOT/home/.hermes" python3 "$REPO/scripts/ai_chat_export.py" --tool Claude >/dev/null 2>&1
MD2=$(ls "$TESTROOT/vault/Claude/Chat Logs/2026/"*.md | head -1)
CNT=$(grep -c "重复的消息" "$MD2" || true)
if [ "$CNT" -ge 2 ]; then
  ok "相同消息两条都导出（cnt=$CNT）"
else
  bad "相同消息只导了 $CNT 条（重复被吞）"
fi

echo
echo "===== 集成测试：$PASS 通过 / $FAIL 失败 ====="
[ "$FAIL" -eq 0 ]