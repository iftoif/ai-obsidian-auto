#!/bin/bash
# 服务器主动拉取所有已加入 Mac 的 AI 客户端会话数据（Claude/Codex/Pi/DSH）
# 先拉主 Mac（固定），再遍历注册标记拉其他节点
# 新架构：Mac 只开 SSH，服务器主动拉取
# 所需环境变量（由 setup-server.sh 注入）：
#   SSH_USER / PRIMARY_MAC_IP — 主 Mac 连接信息
#   OBSIDIAN_VAULT_PATH — 服务器 vault 路径（默认 $HOME/obsidian）
set -uo pipefail


# 配置兜底：优先环境变量（systemd 注入），回退 source 仓库 .env（手工部署路径）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$REPO_DIR/.env" ]; then
  set -a; . "$REPO_DIR/.env"; set +a
fi

PRIMARY_MAC_IP="${PRIMARY_MAC_IP:-}"
SSH_USER="${SSH_USER:-}"
# 服务器主机名：优先环境变量，回退系统 hostname（避免空串导致 case 模式 ** 匹配一切）
SERVER_HOSTNAME="${SERVER_HOSTNAME:-$(hostname -s 2>/dev/null || hostname 2>/dev/null || echo '')}"

VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
NODES_DIR="$VAULT/.hermes-nodes"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOG="$HERMES_HOME/logs/mac-session-pull.log"

mkdir -p "$(dirname "$LOG")" "$HOME/.claude/projects" "$HOME/.codex/sessions" "$HOME/.pi/agent/sessions" "$HOME/.dsh/sessions"
exec >>"$LOG" 2>&1
echo "=== mac-session-pull $(date +%F_%T) ==="

# 失败计数：任一节点任一客户端拉取失败都记账，脚本最终以非零退出
# （否则 rsync 失败被管道吞掉，日志显示 ✅、timer 绿，数据其实没同步）
PULL_FAILED=0

# rsync 的 ssh 也要带超时：探测阶段的 ConnectTimeout 不会传递给 rsync 的
# ssh 子进程，半开连接可阻塞数小时
RSYNC_SSH="ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o BatchMode=yes"

# 单目录拉取：远端存在才拉，失败 fail-loudly 并记账
# exit 24（源文件传输中消失）在活跃会话目录属常见良性情况，放行
pull_dir() {
  local user="$1" ip="$2" label="$3" remote="$4" local_dir="$5"
  if ! ssh -o ConnectTimeout=8 -o BatchMode=yes "$user@$ip" "test -d $remote" 2>/dev/null; then
    return 0
  fi
  rsync -avz -e "$RSYNC_SSH" "$user@$ip:$remote/" "$local_dir/" 2>&1 | tail -1
  local rc=${PIPESTATUS[0]}
  if [ "$rc" -eq 0 ] || [ "$rc" -eq 24 ]; then
    echo "  ✅ $label 会话已拉取"
  else
    echo "  ❌ $label 会话拉取失败（rsync exit $rc）"
    PULL_FAILED=$((PULL_FAILED + 1))
  fi
}

# 拉取函数：ssh user@ip 拉取 Claude/Codex/Pi/DSH 会话
pull_node() {
  local user="$1" ip="$2" host="$3"
  echo "--- 处理节点: $host ($ip, user=$user) ---"
  if ! ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o BatchMode=yes "$user@$ip" "exit" 2>/dev/null; then
    echo "  ⚠️ $host 不可达，跳过"
    return
  fi
  # 检测各会话目录是否存在（避免 rsync error 23）
  pull_dir "$user" "$ip" "Claude" "~/.claude/projects" "$HOME/.claude/projects"
  pull_dir "$user" "$ip" "Codex"  "~/.codex/sessions"  "$HOME/.codex/sessions"
  pull_dir "$user" "$ip" "Pi"     "~/.pi/agent/sessions" "$HOME/.pi/agent/sessions"
  pull_dir "$user" "$ip" "DSH"    "~/.dsh/sessions"    "$HOME/.dsh/sessions"
}

# 1. 主 Mac（固定，当前架构核心工作机；连接信息由环境变量注入）
if [ -n "$PRIMARY_MAC_IP" ] && [ -n "$SSH_USER" ]; then
  pull_node "$SSH_USER" "$PRIMARY_MAC_IP" "主Mac"
fi

# 2. 从注册标记遍历其他节点（新加入的机器）
if [ -d "$NODES_DIR" ]; then
  for f in "$NODES_DIR"/*.json; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    # 跳过主 Mac 与服务器自身的标记（主 Mac 已单独处理；服务器自身标记用 SERVER_HOSTNAME 匹配）
    # 注意：SERVER_HOSTNAME 为空时 case 模式会变成 ** 匹配一切，必须先判非空
    if [ -n "$SERVER_HOSTNAME" ]; then
      case "$fname" in
        *${SERVER_HOSTNAME}*) continue ;;
      esac
    fi
    NODE_IP=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("lan_ip",""))' 2>/dev/null)
    NODE_USER=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("user",""))' 2>/dev/null)
    [ -z "$NODE_USER" ] && NODE_USER="$SSH_USER"
    NODE_HOST=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("hostname","?"))' 2>/dev/null)
    [ -z "$NODE_IP" ] && continue
    # IP 格式/范围校验（与 node-discovery 一致）：防恶意 json 让服务器
    # 尝试 SSH 到任意地址（IP 投毒）
    if ! python3 - "$NODE_IP" <<'PYEOF' 2>/dev/null
import re, sys
ip = sys.argv[1]
assert re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", ip)
assert all(0 <= int(x) <= 255 for x in ip.split("."))
PYEOF
    then
      echo "  ⚠️ 跳过非法 IP 的注册标记: $fname ($NODE_IP)" >> "$LOG"
      continue
    fi
    # 跳过主 Mac 自身的注册标记（第 1 段已单独处理，避免重复拉取）
    [ -n "$PRIMARY_MAC_IP" ] && [ "$NODE_IP" = "$PRIMARY_MAC_IP" ] && continue
    pull_node "$NODE_USER" "$NODE_IP" "$NODE_HOST"
  done
fi

# fail-loudly：有任何客户端目录拉取失败则非零退出（systemd 会标记 failed，
# 便于 journalctl / production-check 发现，而不是静默假成功）
if [ "$PULL_FAILED" -gt 0 ]; then
  echo "=== 拉取完成（有 $PULL_FAILED 项失败）$(date +%F_%T) ==="
  exit 1
fi
echo "=== 拉取完成 $(date +%F_%T) ==="
