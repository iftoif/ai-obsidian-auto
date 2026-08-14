#!/usr/bin/env bash
# AI Obsidian Auto — 服务器一键部署
# 用法：先复制 .env.example 为 .env 并填写，然后运行本脚本
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# 加载配置（.env 是唯一配置源）
if [ -f "$REPO_DIR/.env" ]; then
  set -a; source "$REPO_DIR/.env"; set +a
else
  echo "❌ 请先复制 .env.example 为 .env 并填写你的配置"
  echo "   cp .env.example .env"
  exit 1
fi

# 验证必填项
[ -n "${OBSIDIAN_VAULT_PATH}" ] || { echo "❌ 请填写 OBSIDIAN_VAULT_PATH"; exit 1; }
[ -n "${PRIMARY_MAC_IP}" ] || { echo "❌ 请填写 PRIMARY_MAC_IP"; exit 1; }
[ -n "${SSH_USER}" ] || { echo "❌ 请填写 SSH_USER"; exit 1; }

echo "===== AI Obsidian Auto 服务器部署 ====="
echo "Vault: ${OBSIDIAN_VAULT_PATH}"
echo "主 Mac: ${SSH_USER}@${PRIMARY_MAC_IP}"
echo ""

# 0. 派生变量（MAC_USER 留空时回退到 SSH_USER）
export MAC_USER="${MAC_USER:-$SSH_USER}"

# 1. 创建 Vault 目录
mkdir -p "${OBSIDIAN_VAULT_PATH}/Wiki/Sources" \
         "${OBSIDIAN_VAULT_PATH}/Wiki/Concepts" \
         "${OBSIDIAN_VAULT_PATH}/Wiki/Entities" \
         "${OBSIDIAN_VAULT_PATH}/Wiki/Topics" \
         "${OBSIDIAN_VAULT_PATH}/Context" \
         "${OBSIDIAN_VAULT_PATH}/Shared/Lessons"
echo "✅ Vault 目录结构已创建"

# 脚本直接从仓库路径运行（git pull 更新立即生效，无需拷贝步骤；
# 仓库移动后重跑本脚本即可）。脚本内部互调用同目录引用（$SCRIPT_DIR）。

# 2. 创建 systemd 定时器（拉取 + 发现 + 蒸馏 + 索引 + Git + 自愈）
mkdir -p "$HOME/.config/systemd/user"
SYSTEMD="$HOME/.config/systemd/user"

# 通用 service 环境变量块（注入 .env 里的变量，保证 systemd 直调时可用）
ENV_BLOCK="[Service]
Type=oneshot
Environment=\"OBSIDIAN_VAULT_PATH=${OBSIDIAN_VAULT_PATH}\"
Environment=\"SSH_USER=${SSH_USER}\"
Environment=\"PRIMARY_MAC_IP=${PRIMARY_MAC_IP}\"
Environment=\"MAC_USER=${MAC_USER}\"
Environment=\"HERMES_HOME=${HERMES_HOME:-$HOME/.hermes}\""

# 写一个 service + timer 的辅助函数
write_unit() {
  local name="$1" script="$2" schedule="$3" bootsec="${4:-10min}"
  {
    echo "[Unit]"
    echo "Description=$name"
    echo "$ENV_BLOCK"
    echo "ExecStart=$REPO_DIR/scripts/$script"   # 活代码路径：git pull 更新立即生效
  } > "$SYSTEMD/$name.service"
  cat > "$SYSTEMD/$name.timer" <<TEOF
[Unit]
Description=Timer for $name

[Timer]
OnBootSec=$bootsec
OnUnitActiveSec=$schedule

[Install]
WantedBy=timers.target
TEOF
  echo "✅ $name 单元已生成"
}

write_unit "vault-pull" "vault-pull.sh" "1h" "12min"
write_unit "node-discovery" "node-discovery.sh" "1h" "10min"
write_unit "mac-session-pull" "mac-session-pull.sh" "1h" "15min"
write_unit "hermes-self-heal" "hermes-self-heal.sh" "1h" "5min"

# 蒸馏/索引/Chroma 用固定时刻（非固定间隔）
{
  echo "[Unit]"
  echo "Description=obsidian-server-distill"
  echo "$ENV_BLOCK"
  echo "Environment=\"AI_DISTILL_PROVIDER=${AI_DISTILL_PROVIDER:-openai-codex}\""
  echo "Environment=\"AI_DISTILL_MODEL=${AI_DISTILL_MODEL:-gpt-5.6-luna}\""
  echo "Environment=\"FALLBACK_PROVIDERS_CSV=${FALLBACK_PROVIDERS_CSV:-}\""
  echo "Environment=\"FALLBACK_MODELS_CSV=${FALLBACK_MODELS_CSV:-}\""
  echo "ExecStart=$REPO_DIR/scripts/server-wiki-distill.sh"
} > "$SYSTEMD/obsidian-server-distill.service"
cat > "$SYSTEMD/obsidian-server-distill.timer" <<TEOF
[Unit]
Description=Timer for obsidian-server-distill

[Timer]
OnCalendar=*-*-* 01,05,09,13,17,21:20:00
Persistent=true

[Install]
WantedBy=timers.target
TEOF
echo "✅ obsidian-server-distill 单元已生成"

{
  echo "[Unit]"
  echo "Description=obsidian-server-index"
  echo "$ENV_BLOCK"
  echo "ExecStart=$REPO_DIR/scripts/obsidian_cron.sh"
} > "$SYSTEMD/obsidian-server-index.service"
cat > "$SYSTEMD/obsidian-server-index.timer" <<TEOF
[Unit]
Description=Timer for obsidian-server-index

[Timer]
OnCalendar=*-*-* *:10:00
Persistent=true

[Install]
WantedBy=timers.target
TEOF
echo "✅ obsidian-server-index 单元已生成"

write_unit "wiki-git-autocommit" "wiki_git_autocommit.sh" "1h" "20min"

# Chroma 语义索引（每周日 04:00）
{
  echo "[Unit]"
  echo "Description=obsidian-server-chroma"
  echo "$ENV_BLOCK"
  echo "ExecStart=$REPO_DIR/scripts/server-wiki-chroma.sh"
} > "$SYSTEMD/obsidian-server-chroma.service"
cat > "$SYSTEMD/obsidian-server-chroma.timer" <<TEOF
[Unit]
Description=Timer for obsidian-server-chroma

[Timer]
OnCalendar=Sun 04:00:00
Persistent=true

[Install]
WantedBy=timers.target
TEOF
echo "✅ obsidian-server-chroma 单元已生成"

# 3. 启用所有定时器
systemctl --user daemon-reload
for t in vault-pull node-discovery mac-session-pull hermes-self-heal obsidian-server-distill obsidian-server-index wiki-git-autocommit obsidian-server-chroma; do
  systemctl --user enable "$t.timer"
  systemctl --user start "$t.timer"
  echo "✅ $t.timer 已启用"
done

# 4. 配置 crontab 导出调度
# 注意：全新服务器 crontab -l 无输出时 grep -v 退出码 1，set -e 会杀死子 shell
#       → echo 不执行、crontab 收到空输入（清空 crontab）、脚本 exit 1。
#       用 || true 保证 grep 失败不中断，echo 始终执行。
CRON_LINE="3 * * * * $REPO_DIR/scripts/export-all.sh >> $HOME/export.log 2>&1"
(crontab -l 2>/dev/null | grep -v "export-all.sh" || true; echo "$CRON_LINE") | crontab -
echo "✅ crontab 导出调度已配置（每小时 3 分）"

echo ""
echo "===== 部署完成 ====="
echo "下一步："
echo "  1. 配置 Hermes Gateway（微信/Telegram）"
echo "  2. 在工作站执行加入流程（见 docs/join-flow.md）"
echo "  3. 配置 rclone 加密网盘备份"
