#!/bin/bash
# 服务器主动拉取主 Mac 的 iCloud Vault（注册标记 + 手动编辑 + Chat Logs 回流）
# 新架构：Mac 不装同步脚本，服务器主动 SSH 拉取
# 所需环境变量（由 setup-server.sh 注入，或手动 export）：
#   SSH_USER          — 主 Mac SSH 用户名（如 your_user）
#   PRIMARY_MAC_IP    — 主 Mac 局域网 IP（如 192.168.x.x）
#   MAC_USER          — 主 Mac 本地用户名（iCloud 路径用，如 your_user）
#   OBSIDIAN_VAULT_PATH — 服务器 vault 路径（默认 $HOME/obsidian）
set -uo pipefail

# 配置兜底：优先环境变量（systemd 注入），回退 source 仓库 .env（手工部署路径）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$REPO_DIR/.env" ]; then
  set -a; . "$REPO_DIR/.env"; set +a
fi

# 注意顺序：先初始化基础变量，再做嵌套回退（避免 set -u 下 unbound）
PRIMARY_MAC_IP="${PRIMARY_MAC_IP:-}"
SSH_USER="${SSH_USER:-}"
MAC_USER="${MAC_USER:-${SSH_USER:-}}"
SERVER_VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOG="$HERMES_HOME/logs/vault-pull.log"

if [ -z "$PRIMARY_MAC_IP" ] || [ -z "$SSH_USER" ]; then
  echo "⚠️ 未配置 PRIMARY_MAC_IP / SSH_USER，跳过"
  exit 0
fi

MAC="$SSH_USER@$PRIMARY_MAC_IP"
MAC_VAULT="/Users/$MAC_USER/Library/Mobile Documents/com~apple~CloudDocs/obsidian/"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== vault-pull $(date +%F_%T) ==="

# 检测主 Mac 是否可达
if ! ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o BatchMode=yes "$MAC" "exit" 2>/dev/null; then
  echo "⚠️ 主 Mac 不可达，跳过"
  exit 0
fi

# 拉取：主 Mac iCloud Vault → 服务器
# 远程路径含空格（Mobile Documents）：单引号包裹路径整体传给远程 shell。
# 不用 --protect-args：远端 rsync 版本较老（macOS 自带 2.6.9）时 -s
# 会协议错误（实测 rsync 3.4.1 + 老远端 connection closed）
# -e ssh：给 rsync 自己的 ssh 连接也带上超时（探测阶段的 ConnectTimeout
# 不会传递给 rsync 的 ssh 子进程，半开连接会阻塞数小时）
rsync -avz -e "ssh -o ConnectTimeout=8 -o ServerAliveInterval=5 -o ServerAliveCountMax=2 -o BatchMode=yes" \
  --exclude=".obsidian/workspace.json" --exclude=".trash/" \
  "$MAC:'$MAC_VAULT'" \
  "$SERVER_VAULT/" 2>&1 | tail -5
RSYNC_RC=${PIPESTATUS[0]}
# fail-loudly：rsync 失败必须报错退出，不能无条件打 ✅（否则数据未同步
# 而日志显示成功、timer 绿、健康检查也发现不了）。
# exit 24（源文件传输中消失）是 iCloud 活动目录的常见良性情况，放行。
if [ "$RSYNC_RC" -eq 0 ] || [ "$RSYNC_RC" -eq 24 ]; then
  echo "✅ iCloud Vault 已拉取到服务器"
else
  echo "❌ rsync 拉取失败（exit $RSYNC_RC）——Vault 未同步，请检查主 Mac 磁盘/权限/网络"
  exit 1
fi

echo "=== 完成 $(date +%F_%T) ==="
