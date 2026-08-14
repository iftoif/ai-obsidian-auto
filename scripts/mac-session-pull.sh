#!/bin/bash
# 服务器主动拉取所有已加入 Mac 的 AI 客户端会话数据（Claude/Codex/Pi/DSH）
# 先拉主 Mac（固定），再遍历注册标记拉其他节点
# 新架构：Mac 只开 SSH，服务器主动拉取
# 所需环境变量（由 setup-server.sh 注入）：
#   SSH_USER / PRIMARY_MAC_IP — 主 Mac 连接信息
#   OBSIDIAN_VAULT_PATH — 服务器 vault 路径（默认 $HOME/obsidian）
set -uo pipefail

PRIMARY_MAC_IP="${PRIMARY_MAC_IP:-}"
SSH_USER="${SSH_USER:-}"
SERVER_HOSTNAME="${SERVER_HOSTNAME:-}"

VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
NODES_DIR="$VAULT/.hermes-nodes"
LOG="$HOME/.hermes/logs/mac-session-pull.log"

mkdir -p "$(dirname "$LOG")" "$HOME/.claude/projects" "$HOME/.codex/sessions" "$HOME/.pi/agent/sessions" "$HOME/.dsh/sessions"
exec >>"$LOG" 2>&1
echo "=== mac-session-pull $(date +%F_%T) ==="

# 拉取函数：ssh user@ip 拉取 Claude/Codex/Pi/DSH 会话
pull_node() {
  local user="$1" ip="$2" host="$3"
  echo "--- 处理节点: $host ($ip, user=$user) ---"
  if ! ssh -o ConnectTimeout=8 -o BatchMode=yes "$user@$ip" "exit" 2>/dev/null; then
    echo "  ⚠️ $host 不可达，跳过"
    return
  fi
  # 检测各会话目录是否存在（避免 rsync error 23）
  if ssh -o BatchMode=yes "$user@$ip" "test -d ~/.claude/projects" 2>/dev/null; then
    rsync -avz "$user@$ip:~/.claude/projects/" "$HOME/.claude/projects/" 2>&1 | tail -1
    echo "  ✅ Claude 会话已拉取"
  fi
  if ssh -o BatchMode=yes "$user@$ip" "test -d ~/.codex/sessions" 2>/dev/null; then
    rsync -avz "$user@$ip:~/.codex/sessions/" "$HOME/.codex/sessions/" 2>&1 | tail -1
    echo "  ✅ Codex 会话已拉取"
  fi
  if ssh -o BatchMode=yes "$user@$ip" "test -d ~/.pi/agent/sessions" 2>/dev/null; then
    rsync -avz "$user@$ip:~/.pi/agent/sessions/" "$HOME/.pi/agent/sessions/" 2>&1 | tail -1
    echo "  ✅ Pi 会话已拉取"
  fi
  if ssh -o BatchMode=yes "$user@$ip" "test -d ~/.dsh/sessions" 2>/dev/null; then
    rsync -avz "$user@$ip:~/.dsh/sessions/" "$HOME/.dsh/sessions/" 2>&1 | tail -1
    echo "  ✅ DSH 会话已拉取"
  fi
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
    case "$fname" in
      *${SERVER_HOSTNAME}*) continue ;;
    esac
    NODE_IP=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("lan_ip",""))' 2>/dev/null)
    NODE_USER=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("user",""))' 2>/dev/null)
    [ -z "$NODE_USER" ] && NODE_USER="$SSH_USER"
    NODE_HOST=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("hostname","?"))' 2>/dev/null)
    [ -z "$NODE_IP" ] && continue
    pull_node "$NODE_USER" "$NODE_IP" "$NODE_HOST"
  done
fi

echo "=== 拉取完成 $(date +%F_%T) ==="
