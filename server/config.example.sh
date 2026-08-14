# 服务器配置模板 — 复制为 config.sh 并填入你的信息
# 开源版：所有个人路径/凭据已脱敏，请填写你自己的值
#
# 注意：推荐统一使用 .env 配置（cp .env.example .env），本文件是传统方式，
# 两者变量名完全一致，setup-server.sh 优先读 .env。

# ── 服务器信息 ──
export SERVER_USER="你的用户名"           # 服务器 SSH 用户名（如 your_user）
export SERVER_HOSTNAME="你的服务器主机名"  # 仅文档/通知用
export OBSIDIAN_VAULT_PATH="$HOME/obsidian"  # 服务器 Vault 路径
export HERMES_HOME="$HOME/.hermes"           # Hermes 数据目录

# ── 工作站信息（主 Mac，单台；多机靠注册标记自动发现）──
export PRIMARY_MAC_IP="你的主Mac局域网IP"   # 如 192.168.x.x
export SSH_USER="你的主Mac用户名"           # SSH 登录名（如 your_user）
export MAC_USER="你的Mac用户名"             # iCloud 路径用（如 your_user）

# ── 蒸馏 provider（fallback 链用）──
export AI_DISTILL_PROVIDER="你的provider"   # 主模型 provider（如 openai-codex）
export AI_DISTILL_MODEL="你的model"         # 主模型（如 your-model）
export DEEPSEEK_API_KEY=""                  # 兜底1 API key（可选）
export KIMI_API_KEY=""                      # 兜底2 API key（可选）

# ── 通知配置（Telegram，可选）──
export TELEGRAM_BOT_TOKEN="你的bot token"   # 建 Bot 后获取
export TELEGRAM_CHAT_ID="你的chat id"

# ── 备份配置（rclone 加密网盘，可选）──
export RCLONE_REMOTE="你的rclone远程名"    # 如 crypt_backup
export RCLONE_BACKUP_DIR="backup/obsidian"
