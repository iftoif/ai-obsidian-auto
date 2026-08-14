# 部署手册

> 从零搭建这套生态的操作手册。所有占位符 `<PLACEHOLDER>` 需替换为你的实际值。

## 0. 目标拓扑

```text
┌─ 服务器（Linux，7×24）─────────────────────────┐
│  • Hermes Gateway（微信/Telegram 消息平台）     │
│  • systemd timers：拉取/导出/蒸馏/索引/备份     │
│  • crontab：三个导出任务                        │
│  • SQLite + Chroma + Git 仓库                   │
└───────────────┬────────────────────────────────┘
                │ SSH + rsync（每小时，服务器主动）
┌───────────────┴────────────────────────────────┐
│  Mac 工作站 ×N                                 │
│  • 只开 SSH + 加服务器公钥 + 写注册标记        │
│  • AI 客户端：Claude Code / Codex / Pi / DSH   │
│  • iCloud Obsidian Vault（编辑入口）            │
└────────────────────────────────────────────────┘
```

## 1. 服务器准备

### 1.1 基础

```bash
# Ubuntu 24.04 建议
sudo apt update && sudo apt install -y python3 python3-venv rsync cron sqlite3 git

# 用户（本仓库以普通用户运行，不推荐 root）
sudo adduser <SERVER_USER>
sudo usermod -aG sudo <SERVER_USER>
```

### 1.2 目录

```bash
mkdir -p ~/obsidian ~/.hermes/scripts ~/.hermes/logs ~/.hermes/data/obsidian ~/.hermes/backups
mkdir -p ~/.claude/projects ~/.codex/sessions ~/.pi/agent/sessions ~/.dsh/sessions
```

## 2. 脚本部署

把本仓库 `scripts/` 下所有文件复制到服务器 `~/.hermes/scripts/`，并 `chmod +x`。

```bash
chmod +x ~/.hermes/scripts/*.sh ~/.hermes/scripts/*.py
```

### 2.1 配置（唯一来源：.env）

复制 `.env.example` 为 `.env`，填入以下变量：

| 变量 | 含义 | 示例 |
|---|---|---|
| `SERVER_USER` | 服务器 SSH 用户名（文档/通知用） | `your_user` |
| `SERVER_HOSTNAME` | 服务器主机名（文档/通知用） | `my-server` |
| `OBSIDIAN_VAULT_PATH` | 服务器 Vault 路径 | `$HOME/obsidian` |
| `HERMES_HOME` | Hermes 数据目录 | `$HOME/.hermes` |
| `PRIMARY_MAC_IP` | 主 Mac 的局域网 IP | `192.168.x.x` |
| `SSH_USER` | 主 Mac SSH 登录名 | `your_user` |
| `MAC_USER` | 主 Mac 本地用户名（iCloud 路径用，留空则等于 SSH_USER） | `your_user` |
| `AI_DISTILL_PROVIDER` | 蒸馏主模型 provider | `your-provider` |
| `AI_DISTILL_MODEL` | 蒸馏主模型 | `your-model` |
| `DEEPSEEK_API_KEY` / `KIMI_API_KEY` | fallback 链 key（可选） | — |
| `RCLONE_REMOTE` | rclone 备份远程:目录（可选） | `crypt_remote:backup/obsidian` |

> `setup-server.sh` 和所有脚本都自动加载 `.env`；`.env` 已被 `.gitignore` 排除，绝不提交。

### 2.2 依赖

```bash
# Python 依赖
python3 -m venv ~/.hermes/obsidian-backup-env
~/.hermes/obsidian-backup-env/bin/pip install zstandard chromadb

# Hermes（消息平台 + 蒸馏执行器，按需安装）
# https://github.com/your-hermes-fork  # 本项目使用私有 Hermes Agent
```

## 3. systemd timers（服务器）

参考 `templates/systemd/` 下的 unit 文件，安装到 `~/.config/systemd/user/`：

```bash
mkdir -p ~/.config/systemd/user
cp templates/systemd/*.service templates/systemd/*.timer ~/.config/systemd/user/

# 关键前置：开启 linger，让定时器在无登录会话时也运行（常见翻车点）
loginctl enable-linger $USER

# 启用（示例：拉取 + 蒸馏 + 索引 + Git + 自愈）
systemctl --user enable --now mac-session-pull.timer vault-pull.timer node-discovery.timer
systemctl --user enable --now obsidian-server-distill.timer obsidian-server-index.timer
systemctl --user enable --now wiki-git-autocommit.timer hermes-self-heal.timer
systemctl --user enable --now obsidian-server-chroma.timer

# 可选：备份 timer（rclone 加密到远程存储）
sudo systemctl enable --now obsidian-rclone-backup.timer
```

### 3.1 蒸馏服务需要 secret store

蒸馏有 provider 降级链（deepseek/kimi 兜底），需要 API key。创建 `~/.config/hermes/secret-store/hermes.env`（mode 600）并在蒸馏 service 加 EnvironmentFile：

```ini
# ~/.config/systemd/user/obsidian-server-distill.service.d/secret-store.conf
[Service]
EnvironmentFile=-%h/.config/hermes/secret-store/hermes.env
```

## 4. crontab（导出）

> ⚠️ **二选一**，不要两个方案都配（会导致同一导出每小时被跑两遍）：

### 方案 A（推荐）：单条 cron 跑 export-all.sh

`setup-server.sh` 自动注册的就是这条，手动配也一样：

```cron
3 * * * *  <REPO_DIR>/scripts/export-all.sh >> $HOME/export.log 2>&1
```

export-all.sh 内部顺序执行 Hermes/Claude/Pi/DSH/Codex 全部导出，并检查每个环节退出码（失败 exit 1）。

### 方案 B（替代）：三条 cron 分开调度

想给不同导出设置不同频率/独立日志时用这条路径（脚本内部同样检查退出码，失败不会假报成功）：

```bash
crontab -e
```

```cron
0 * * * *  /home/<SERVER_USER>/.hermes/scripts/chat_export_cron.sh >> /home/<SERVER_USER>/.hermes/logs/chat_export.log 2>&1
3 * * * *  /home/<SERVER_USER>/.hermes/scripts/ai_chat_export_cron.sh >> /home/<SERVER_USER>/.hermes/logs/ai_chat_export.log 2>&1
7 * * * *  /home/<SERVER_USER>/.hermes/scripts/codex_chat_export_cron.sh >> /home/<SERVER_USER>/.hermes/logs/codex_chat_export.log 2>&1
```

## 5. Mac 工作站加入

### 5.1 开 SSH

```bash
# 系统设置 → 通用 → 共享 → 远程登录；或
sudo systemsetup -setremotelogin on
```

### 5.2 加服务器公钥

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "ssh-ed25519 AAAA... <SERVER_USER>@<SERVER_HOSTNAME>-rsync" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 5.3 写注册标记

```bash
NODES_DIR="$HOME/Library/Mobile Documents/com~apple~CloudDocs/obsidian/.hermes-nodes"
mkdir -p "$NODES_DIR"
cat > "$NODES_DIR/$(hostname -s)-$(date +%Y%m%d-%H%M%S).json" <<EOF
{
  "hostname": "$(hostname)",
  "role": "workstation",
  "user": "$(whoami)",
  "joined_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "os": "$(uname -s) $(uname -m)",
  "lan_ip": "$(ipconfig getifaddr en0 2>/dev/null || echo '')"
}
EOF
```

服务器会在 1 小时内自动发现并开始拉取。

### 5.4 验证

```bash
# 服务器上
ls ~/obsidian/.hermes-nodes/              # 应有新节点标记
journalctl --user -u node-discovery --since "1h"
journalctl --user -u mac-session-pull --since "1h"
```

## 6. 首次引导

1. 在 iCloud Vault 建 `CLAUDE.md` + `Context/` + `Wiki/` 骨架（见 `templates/vault-skeleton/`）
2. 手动跑一次全链路验证：

```bash
# 拉取 → 导出 → 蒸馏（dry-run）
bash ~/.hermes/scripts/mac-session-pull.sh
bash ~/.hermes/scripts/ai_chat_export_cron.sh
bash ~/.hermes/scripts/ai_chat_unified_distill_cron.sh --dry-run
```

3. 确认 `~/obsidian/*/Chat Logs/` 出现 Raw md，`Wiki/Log.md` 开始追加

## 7. 升级保护（Hermes）

Hermes 升级会覆盖源码。`hermes_patch.py` 自动重放 3 个补丁：

1. `cleanup_image_cache` → no-op（图片永久保留）
2. 静默 shutdown 通知
3. systemd EnvironmentFile（secret store 注入）

升级后验证：

```bash
systemctl --user restart hermes-gateway
journalctl --user -u hermes-gateway --since "5m" | grep -E "patch|patched"
```

## 8. 排障速查

| 症状 | 排查 |
|---|---|
| Mac 会话没被拉取 | `journalctl --user -u mac-session-pull`；检查节点可达 + 注册标记 user/lan_ip 正确 |
| Chat Logs 没生成 | 手动跑 `ai_chat_export_cron.sh` 看错误；确认 OBSIDIAN_VAULT_PATH 指向服务器 vault |
| 蒸馏失败 | `journalctl --user -u obsidian-server-distill`；检查 secret store 加载 + provider 降级链日志 |
| 导出写错位置 | 确认 `default_vault()`：Linux 上应回退 `~/obsidian`，不是 Mac iCloud 路径 |
| rsync error 23 | 客户端未装某工具 → `test -d` 已容错；确认目录名拼写 |

## 9. 常见坑

1. **导出脚本的 VAULT 默认值**：曾因默认值指向废弃的 `~/Documents/ObsidianVault` 导致写空——所有脚本统一用 `OBSIDIAN_VAULT_PATH` 环境变量 + `~/obsidian` 回退
2. **双向同步别用 `--delete`**：会删掉另一端的蒸馏产物
3. **Hermes cron job 机制不可靠**（claim/drift），蒸馏用「脚本直跑」而不是 LLM cron job
4. **蒸馏失败检测**：hermes chat 失败退出码可能为 0，要用输出内容判断（`API call failed` / `No API key` / `HTTP 4xx`）
