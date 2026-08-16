#!/bin/bash
# 服务器 → Mac 回传蒸馏产物（Wiki + Lessons），解决 Mac Obsidian 看不到服务器蒸馏内容的问题。
# 安全约束：
#   1. 只推 Wiki/ 和 */Lessons/（蒸馏产物只写这两类，Chat Logs 是 Mac 源，绝不回推）。
#   2. 不带 --delete（绝不删 Mac 任何文件）。
#   3. --ignore-existing（只推 Mac 没有的文件，绝不覆盖 Mac 手动编辑/已有内容）。
#
# 环境变量（见 .env.example）：
#   PRIMARY_MAC_IP    — 主 Mac 局域网 IP
#   SSH_USER          — 主 Mac SSH 登录名
#   MAC_USER          — 主 Mac 本地用户名（iCloud 路径 /Users/<MAC_USER>；留空=SSH_USER）
#   OBSIDIAN_VAULT_PATH — 服务器 vault 路径（默认 $HOME/obsidian）
#   HERMES_HOME       — Hermes 数据目录（默认 $HOME/.hermes）
set -uo pipefail

PRIMARY_MAC_IP="${PRIMARY_MAC_IP:-}"
SSH_USER="${SSH_USER:-}"
MAC_USER="${MAC_USER:-${SSH_USER:-}}"
SERVER_VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"

if [ -z "$PRIMARY_MAC_IP" ] || [ -z "$SSH_USER" ]; then
  echo "⚠️ 未配置 PRIMARY_MAC_IP / SSH_USER，跳过"
  exit 0
fi

MAC="$SSH_USER@$PRIMARY_MAC_IP"
MAC_VAULT="/Users/$MAC_USER/Library/Mobile Documents/com~apple~CloudDocs/obsidian"
LOG="$HERMES_HOME/logs/vault-push.log"
SSH_OPTS="-e ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o BatchMode=yes"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== vault-push $(date +%F_%T) ==="

if ! ssh -o ConnectTimeout=8 -o BatchMode=yes "$MAC" "exit" 2>/dev/null; then
  echo "⚠️ 主 Mac 不可达，跳过"
  exit 0
fi

for d in Wiki Hermes/Lessons Codex/Lessons Claude/Lessons Pi/Lessons Shared/Lessons; do
  if [ -d "$SERVER_VAULT/$d" ]; then
    echo "--- 回传 $d ---"
    rsync -avz $SSH_OPTS --ignore-existing \
      "$SERVER_VAULT/$d/" \
      "$MAC:$MAC_VAULT/$d/" 2>&1 | tail -2
  fi
done

echo "✅ 蒸馏产物已回传 Mac（不覆盖 Mac 已有文件）"
echo "=== 完成 $(date +%F_%T) ==="
