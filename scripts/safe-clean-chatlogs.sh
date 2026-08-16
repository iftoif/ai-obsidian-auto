#!/usr/bin/env bash
# 安全清理聊天记录：先检查蒸馏状态，确保蒸馏完成再删
# 用法：
#   safe-clean-chatlogs.sh            # 检查模式：列出已蒸馏/未蒸馏
#   safe-clean-chatlogs.sh --distill  # 先触发蒸馏，再检查
#   safe-clean-chatlogs.sh --clean    # 蒸馏完成后删除（需先确认）
#   safe-clean-chatlogs.sh --force    # 强制删除（跳过检查，危险）
set -uo pipefail

VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
STATE_FILE="$HERMES_HOME/data/obsidian/distill_state.json"
DISTILL_SCRIPT="$HERMES_HOME/scripts/ai_chat_unified_distill_cron.sh"
MODEL=""

# 解析参数
ACTION="check"
for arg in "$@"; do
  case "$arg" in
    --distill) ACTION="distill" ;;
    --clean) ACTION="clean" ;;
    --force) ACTION="force" ;;
    *) echo "未知参数: $arg" >&2; exit 2 ;;
  esac
done

# 检查蒸馏状态：返回未蒸馏文件列表
check_pending() {
  python3 - "$VAULT" "$STATE_FILE" << 'PYEOF'
import json, sys
from pathlib import Path
vault = Path(sys.argv[1])
state_path = Path(sys.argv[2])
try:
    state = json.loads(state_path.read_text()).get("files", {})
except Exception:
    state = {}

pending = []
distilled = []
for root in ("Hermes/Chat Logs", "Codex/Chat Logs", "Claude/Chat Logs", "Pi/Chat Logs"):
    d = vault / root
    if not d.exists():
        continue
    for p in sorted(d.rglob("*.md")):
        rel = str(p.relative_to(d))
        if rel.startswith("assets/"):
            continue
        key = str(p.relative_to(vault))
        st = p.stat()
        sig = f"{st.st_mtime_ns}:{st.st_size}"
        if state.get(key) == sig:
            distilled.append(key)
        else:
            pending.append(key)
print(f"STATS|total={len(distilled)+len(pending)}|distilled={len(distilled)}|pending={len(pending)}")
print("===PENDING===")
for k in pending:
    print(k)
PYEOF
}

# 触发蒸馏（如果有未处理的）
run_distill() {
  echo "📡 触发蒸馏处理未蒸馏的 Chat Logs..."
  if [ -x "$DISTILL_SCRIPT" ]; then
    # 必须传 OBSIDIAN_VAULT_PATH + HERMES_HOME，否则蒸馏脚本用错误默认路径
    OBSIDIAN_VAULT_PATH="$VAULT" HERMES_HOME="$HERMES_HOME" "$DISTILL_SCRIPT" 2>&1 | tail -8
  else
    echo "⚠️ 蒸馏脚本不存在: $DISTILL_SCRIPT"
  fi
}

echo "===== 安全清理聊天记录 ====="
echo "Vault: $VAULT"
echo "动作: $ACTION"
echo ""

case "$ACTION" in
  check)
    check_pending
    ;;
  distill)
    run_distill
    echo ""
    echo "===== 蒸馏后重新检查 ====="
    check_pending
    ;;
  clean|force)
    if [ "$ACTION" = "force" ]; then
      echo "⚠️ 强制删除（跳过检查）"
    else
      check_pending
    fi
    echo ""
    echo "⚠️ 确认删除所有 Chat Logs？(yes/no)"
    read -r confirm
    if [ "$confirm" != "yes" ]; then
      echo "已取消"
      exit 0
    fi
    for root in Hermes Codex Claude Pi; do
      d="$VAULT/$root/Chat Logs"
      if [ -d "$d" ]; then
        # 保留 assets（图片），只删 md 日志
        find "$d" -name "*.md" -delete
        echo "✅ 已删除 $root/Chat Logs 的 md 文件"
      fi
    done
    echo "✅ 清理完成（assets 图片保留）"
    ;;
esac
