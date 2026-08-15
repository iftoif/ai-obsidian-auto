#!/usr/bin/env bash
# 生产服务器健康检查 + 已部署修复回归验证
# 用法：bash ~/.hermes/scripts/production-check.sh
# 设计：只读检查，不改任何文件；任一项失败 exit 非零
set -uo pipefail

PASS=0; FAIL=0
ok()  { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
section() { echo; echo "═══ $1 ═══"; }

SCRIPTS="$HOME/.hermes/scripts"

# ── 1. systemd timer 活性（8 个核心）──
section "1. systemd timers"
for t in vault-pull node-discovery mac-session-pull hermes-self-heal obsidian-server-distill obsidian-server-index wiki-git-autocommit obsidian-server-chroma; do
  if systemctl --user is-active "$t.timer" >/dev/null 2>&1; then
    ok "$t.timer active"
  else
    bad "$t.timer 未运行！"
  fi
done

# ── 2. crontab 导出调度存在 ──
section "2. crontab 导出调度"
CRON=$(crontab -l 2>/dev/null || true)
# 用路径段精确匹配：避免 chat_export_cron.sh 与 ai_chat_export_cron.sh /
# codex_chat_export_cron.sh 的子串重叠（一条含全部子串的行会让三查全过）
if echo "$CRON" | grep -q '/ai_chat_export_cron.sh'; then ok "ai_chat_export cron"; else bad "ai_chat_export cron 缺失"; fi
if echo "$CRON" | grep -q '/chat_export_cron.sh'; then ok "chat_export cron"; else bad "chat_export cron 缺失"; fi
if echo "$CRON" | grep -q '/codex_chat_export_cron.sh'; then ok "codex_export cron"; else bad "codex_export cron 缺失"; fi

# ── 3. 已部署修复的回归断言 ──
section "3. 已部署修复回归（2026-08-15 QA 移植）"

# 3.1 ai_chat_export.py: parse_time 微秒/负数、你好不吞、event_hash line_no、fail-closed
if python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import ai_chat_export as ae; assert ae.parse_time(1_700_000_000_000_001).year == 2023; ae.parse_time(-100); assert not ae.is_low_value('你好'); assert ae.event_hash('C','s','u','x',1) != ae.event_hash('C','s','u','x',2)" 2>/dev/null; then
  ok "ai_chat_export: 微秒/负数/你好/event_hash 全部正常"
else
  bad "ai_chat_export 回归断言失败！"
fi
if grep -q 'REDACT-UNAVAILABLE' "$SCRIPTS/ai_chat_export.py"; then
  ok "ai_chat_export: fail-closed 代码存在"
else
  bad "ai_chat_export: fail-closed 缺失！"
fi

# 3.2 obsidian_backup.py: Chroma 前缀补全 + LIKE fallback
if python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import obsidian_backup as ob; assert 'Claude/Chat Logs/' in ob.CHROMA_RAW_CHAT_PREFIXES; assert 'Pi/Chat Logs/' in ob.CHROMA_RAW_CHAT_PREFIXES; assert 'DSH/Chat Logs/' in ob.CHROMA_RAW_CHAT_PREFIXES" 2>/dev/null; then
  ok "obsidian_backup: Chroma Raw 前缀含 Claude/Pi/DSH"
else
  bad "obsidian_backup: Chroma 前缀断言失败！"
fi
# LIKE fallback 存在即可（仓库版与服务器版均带 ESCAPE 通配符转义）
if grep -qE 'LIKE ? OR title LIKE|content LIKE ?' "$SCRIPTS/obsidian_backup.py"; then
  ok "obsidian_backup: 中文 LIKE fallback 存在"
else
  bad "obsidian_backup: LIKE fallback 缺失！"
fi

# 3.3 redact_secrets.py: sec_id 连字符防二次污染
if python3 -c "import sys; sys.path.insert(0, '$SCRIPTS'); import redact_secrets as rs; assert rs.redact_text('[SECRET:api-key:sec_xy-z]', source='t', store=False) == '[SECRET:api-key:sec_xy-z]'" 2>/dev/null; then
  ok "redact_secrets: sec_xy-z 不二次污染"
else
  bad "redact_secrets: 连字符引用被污染！"
fi

# 3.4 mac-session-pull.sh: IP 校验存在
if grep -q '非法 IP' "$SCRIPTS/mac-session-pull.sh"; then
  ok "mac-session-pull: IP 投毒校验存在"
else
  bad "mac-session-pull: IP 校验缺失！"
fi

# 3.5 vault-pull.sh: 已回滚（无 --protect-args）
if grep -q 'protect-args' "$SCRIPTS/vault-pull.sh"; then
  bad "vault-pull: --protect-args 残留（应已回滚）！"
else
  ok "vault-pull: 保持原版（--protect-args 已回滚）"
fi

# ── 4. 回滚备份存在性 ──
section "4. 回滚备份（.bak-qa-20260815）"
for f in ai_chat_export.py obsidian_backup.py redact_secrets.py mac-session-pull.sh; do
  if [ -f "$SCRIPTS/$f.bak-qa-20260815" ]; then
    ok "$f.bak-qa-20260815 存在"
  else
    bad "$f.bak-qa-20260815 缺失！"
  fi
done

# ── 5. 关键服务日志无近期错误 ──
section "5. 最近 30 分钟服务错误"
ERR=$(journalctl --user --since '30 min ago' --no-pager 2>/dev/null | grep -cE 'obsidian.*(error|Traceback|Failed)' || true)
if [ "$ERR" -eq 0 ]; then
  ok "journalctl 无 obsidian 相关错误"
else
  bad "journalctl 有 $ERR 条错误（obsidian 相关）"
fi

# ── 6. 磁盘空间 ──
section "6. 磁盘空间"
DF=$(df -h "$HOME" | tail -1 | awk '{print $5}' | tr -d '%')
if [ "$DF" -lt 90 ]; then
  ok "磁盘使用 $DF%"
else
  bad "磁盘使用 $DF%（>90%）！"
fi

echo
echo "═══════════════════════════════════"
echo "  生产健康检查：$PASS 通过 / $FAIL 失败"
echo "═══════════════════════════════════"

# 失败时发通知（生产实际渠道：微信个人号 DM；Telegram 未配置 bot token）
if [ "$FAIL" -gt 0 ]; then
  HERMES_SEND="$HOME/.hermes/hermes-agent/venv/bin/hermes"
  if [ -x "$HERMES_SEND" ]; then
    TARGET="weixin:o9cq805KD52wqDf3gaepSLqG2aeg@im.wechat"
    echo "🔴 生产健康检查失败：$FAIL 项未通过（$PASS 通过）" | "$HERMES_SEND" send -t "$TARGET" >>"$HOME/.hermes/logs/production-check.log" 2>&1 || true
  fi
fi
[ "$FAIL" -eq 0 ]