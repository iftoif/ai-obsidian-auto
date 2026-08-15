# 保姆级教程：从零跑通

> 面向第一次接触命令行的小白。每一步都解释「在做什么、为什么」。
> 全程约 1~2 小时。中途卡住看 [faq.md](faq.md)。

## 开始前，确认你手上有这些

| 东西 | 怎么确认有 |
|---|---|
| 一台 Linux 服务器 | 能 SSH 登录上去（Ubuntu/Debian 推荐），会 7×24 开机 |
| 一台 Mac | 你正在用的就行，系统设置里能打开「远程登录」 |
| 一个 LLM API key 或订阅 | DeepSeek/Kimi/Z.AI/OpenAI/Anthropic 任一；有 key 就行 |
| 一个微信小号（可选，强烈推荐） | 网关用——手机指挥 AI 的入口 |
| 一个 GitHub 账号 | 下载代码用（不一定要会 git） |

没有 Linux 服务器？见 [faq.md](faq.md)「没有服务器怎么办」。

## 第 1 步：在服务器上下载本项目（5 分钟）

SSH 登录你的服务器，然后：

```bash
# 1) 下载代码
git clone https://github.com/iftoif/ai-obsidian-auto.git
cd ai-obsidian-auto

# 2) 看一眼里面有什么（可选）
ls        # 你会看到 docs/ scripts/ templates/ README.md 等
```

> 说明：`git clone` = 从 GitHub 把代码复制到你服务器上。`cd` = 进入这个目录。

## 第 2 步：填配置（10 分钟）

复制配置模板，然后用编辑器填写：

```bash
# 1) 复制模板为正式配置
cp .env.example .env

# 2) 打开配置（用你会的编辑器，nano 或 vim 都行）
nano .env
```

`.env` 里要填的**只有 5 个值**，其他都有默认值不用动：

```bash
PRIMARY_MAC_IP=192.168.x.x        # ← 你 Mac 的局域网 IP（Mac 上「系统设置→网络→详细信息」里看）
SSH_USER=yourname                 # ← 你 Mac 的登录用户名（终端里 whoami 能看到）
MAC_USER=yourname                  # ← 同上（Mac 本地用户名，一般一样）
OBSIDIAN_VAULT_PATH=$HOME/obsidian # ← 知识库存服务器哪里（默认就行）
AI_DISTILL_PROVIDER=openai-codex # ← 你的蒸馏 LLM provider（ChatGPT 订阅；也支持 deepseek/kimi 等）
AI_DISTILL_MODEL=gpt-5.6-luna     # ← 模型名（与 .env.example 一致）
DEEPSEEK_API_KEY=sk-xxxx           # ← 你的 API key（fallback 链用）
```

> **怎么拿到 Mac 的 IP**：Mac 上「系统设置 → Wi-Fi → 详细信息」里的 IP 地址，一般是 `192.168.x.x`。
> **谁填什么 provider**：有 DeepSeek key 就填 `deepseek`；有 Kimi 就填 `kimi-coding`；有 ChatGPT 订阅就填 `openai-codex`。模型名见各家的文档。

保存退出（nano：`Ctrl+O` 回车 `Ctrl+X`）。

## 第 3 步：在 Mac 上开 SSH（2 分钟）

Mac 上：**系统设置 → 通用 → 共享 → 打开「远程登录」**。

这是给服务器权限：服务器要靠 SSH 定期来 Mac 拉取 AI 聊天记录。

## 第 4 步：把 Mac 的钥匙交给服务器（5 分钟）

服务器要能免密登录你的 Mac，需要把服务器的公钥加到 Mac 上。

在**服务器**上生成密钥（如果还没有）：

```bash
ssh-keygen -t ed25519 -C "server-rsync"   # 一路回车即可
cat ~/.ssh/id_ed25519.pub                   # 显示公钥，复制它
```

在 **Mac** 上，把复制的公钥加进去：

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
echo "粘贴你复制的公钥" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

在**服务器**上验证能不能免密登录：

```bash
ssh yourname@192.168.x.x "echo 连接成功"   # 不输密码就输出「连接成功」= 成了
```

## 第 5 步：跑部署脚本（5 分钟）

回到服务器项目目录，跑一键部署：

```bash
cd ~/ai-obsidian-auto
bash scripts/setup-server.sh
```

看到这些就成功了：

```text
✅ Vault 目录结构已创建
✅ vault-pull 单元已生成
✅ node-discovery 单元已生成
...
✅ crontab 导出调度已配置
===== 部署完成 =====
```

> 说明：这个脚本会创建 7 个「定时任务」（systemd timer），分别负责：拉取会话、发现新机器、蒸馏知识、建索引、Git 提交、自愈。以后它们自动跑，你不用管。

## 第 6 步：验证跑起来了（10 分钟）

### 6.1 立刻手动拉一次会话

```bash
# 在服务器上手动触发一次（不等定时器）
systemctl --user start mac-session-pull.service
systemctl --user start vault-pull.service

# 看日志确认拉到东西
tail -20 ~/.hermes/logs/mac-session-pull.log
```

看到 `✅ Claude 会话已拉取` 之类的字样 = 拉取通了。

### 6.2 手动导出一次

```bash
bash scripts/export-all.sh
```

### 6.3 看 Raw 聊天记录生成

```bash
ls ~/obsidian/Claude/Chat\ Logs/2026/     # 应有 YYYY-MM-DD.md 出现
ls ~/obsidian/Codex/Chat\ Logs/2026/
```

### 6.4 等蒸馏（最长 4 小时）

蒸馏定时器每 4 小时跑一次。想立刻看效果：

```bash
systemctl --user start obsidian-server-distill.service
# 看日志
journalctl --user -u obsidian-server-distill --since "10 min ago" --no-pager | tail -30
```

蒸馏完成后，看知识层：

```bash
ls ~/obsidian/Wiki/           # 应有 Sources/ Concepts/ Entities/ Topics/ 出现内容
tail -30 ~/obsidian/Wiki/Log.md   # 变更日志有记录 = 蒸馏成功
```

## 第 7 步：在 Mac 上看效果（5 分钟）

服务器和 Mac 之间会自动双向同步。你可以：

1. **Obsidian 打开**：把 `~/obsidian`（服务器）或 iCloud 的 Vault 目录用 Obsidian 打开，看到自动生成的 Wiki 页面
2. **验证同步**：服务器上 `~/obsidian` 有新文件后，Mac 的 iCloud Vault 也会出现

> 注意：本教程里 Vault 在服务器 `~/obsidian`。如果你想让 Obsidian 在 Mac 上打开，服务器拉取脚本会把 Mac 的 iCloud Vault 拉过去；反向同步见 [deployment.md](deployment.md)。

## 第 8 步：装网关（强烈推荐，本系统最大价值）（20 分钟）

> 网关让你**用手机指挥 AI**：微信/Telegram 发消息 → AI 回答 → 聊天自动进知识库。

### 8.1 微信网关（国内用户首选）

```bash
# 服务器上，为你的微信小号创建一个网关
hermes gateway add wechat --profile wechat2

# 启动（首次会生成二维码）
systemctl --user start hermes-gateway-wechat2

# 用微信扫二维码登录（建议用微信小号，详见 gateway.md 的风控说明）
```

### 8.2 Telegram 网关（可选，系统通知推荐用它）

```bash
# 1. Telegram 里找 @BotFather，发 /newbot 创建 Bot，拿到 token
# 2. 拿自己的 chat_id：找 @userinfobot，发消息即可
# 3. 配置（.env 或 ~/.hermes/.env）
TELEGRAM_BOT_TOKEN=你的token
TELEGRAM_CHAT_ID=你的chat_id
# 4. 启动
systemctl --user start hermes-gateway
```

### 8.3 验证

手机微信给 Bot 发「你好」，收到 AI 回复 = 通了。

几小时后，这次对话会自动出现在 `~/obsidian/Hermes/Chat Logs/` 并被蒸馏进 Wiki。

> 微信 vs Telegram 怎么选、各自优缺点、能做什么，见 [gateway.md](gateway.md)。

## 跑通之后，日常是什么样

- **手机随时指挥 AI**：微信/Telegram 发消息，AI 干活并自动沉淀
- **你照常用 AI**（Claude Code / Codex / Pi / DSH…装了什么用什么），什么都不用做
- 每小时：服务器自动拉会话、导出
- 每 4 小时：自动蒸馏 → Wiki/Lessons 更新
- 每天：自动 Git 提交 + 加密备份
- 定时推送：晨间/晚间财经简报自动发到你微信
- 系统通知：新机器加入、蒸馏失败等发到 Telegram

## 卡住了？

1. 先看 [faq.md](faq.md)——大概率你的问题有人踩过
2. 看日志：`journalctl --user -u <服务名> --since "1h" --no-pager`
3. 开 GitHub Issue 描述现象 + 贴日志
