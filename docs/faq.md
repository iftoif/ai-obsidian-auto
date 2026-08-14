# 常见问题（FAQ）

> 按「还没开始 / 部署中 / 运行中 / 进阶」分组。没有你的问题？开 Issue。

## 还没开始

### Q: 我没有 Linux 服务器，能跑吗？

**A**: 不能完整跑。这套系统的自动化核心在 7×24 的 Linux 服务器上（systemd timers 只在 Linux 上有）。替代方案：

- 用家里闲置旧电脑装 Ubuntu（成本最低）
- 买一台便宜的 VPS / 云主机（最低配即可，vault 数据量不大）
- 用 NAS（很多 NAS 支持 Docker/Linux）

没有服务器 → 建议直接手写 Obsidian 笔记，或用官方 Sync。

### Q: 一定要 Mac 吗？Windows 行不行？

**A**: 拉取脚本是按 macOS 的目录结构写的（`~/.claude/projects`、iCloud 路径等），Mac 是测试过的。Windows 理论上可以（AI 客户端的会话目录是跨平台的），但：

- `vault-pull.sh` 里的 iCloud 路径是 Mac 专属 → Windows 用户需要自己改这个脚本
- SSH 配置方式不同

建议 Mac；Windows 用户欢迎改完贡献回来。

### Q: 蒸馏一定要花钱吗？

**A**: 蒸馏需要一个可调用的 LLM。省钱方式：

- **已有 ChatGPT 订阅** → 用 `openai-codex` provider，零额外成本
- **DeepSeek / Kimi 的 API** → 蒸馏用量很小（每 4h 处理几条聊天），每月可能几块钱
- 完全不想花钱 → 可以把蒸馏频率改低（改 timer 的 OnCalendar），但不建议完全关掉（那是核心价值）

### Q: 我完全不懂编程，能装吗？

**A**: 能，前提是你**愿意复制粘贴命令**并跟着 [quickstart.md](quickstart.md) 走。涉及的命令都是「复制、粘贴、回车」。真正要理解的就一件事：填 `.env` 那 5 个值。如果连「打开终端」都抗拒，那这个项目不适合你。

### Q: 我的聊天记录会被上传到哪？

**A**: 两层：

1. **存储**：聊天记录只在你的服务器和 Mac 上（纯 Markdown 文件），不上传任何云
2. **蒸馏**：聊天记录会发给**你自己配置的 LLM API**（DeepSeek/Kimi/OpenAI 等）做提炼——这是唯一离开你机器的环节。如果你在意隐私，选一个你信任的 provider，或参考 [security.md](security.md) 了解脱敏机制（API key 等敏感信息在发送前已被替换成占位符）

## 部署中

### Q: `ssh yourname@IP` 一直要我输密码？

**A**: 免密没配好。检查：

```bash
# Mac 上
cat ~/.ssh/authorized_keys    # 服务器公钥在不在里面
chmod 600 ~/.ssh/authorized_keys   # 权限必须是 600
# 服务器上试
ssh -v yourname@IP "echo ok"   # -v 看详细错误
```

### Q: setup-server.sh 报「请先复制 .env.example 为 .env」？

**A**: 你还没创建 `.env` 文件。执行：

```bash
cp .env.example .env
nano .env   # 填你的值
```

### Q: 部署脚本跑到一半报错？

**A**: `setup-server.sh` 是幂等的（重复跑无害）。修好问题后直接重跑即可。常见错误：

- `.env` 里某个值没填（`请填写 PRIMARY_MAC_IP`）→ 填上重跑
- `systemctl --user` 报错 → 确认你登录的是**用户 session**（不是 root），`loginctl enable-linger $USER` 开启常驻

## 运行中

### Q: 聊天记录没有出现在 vault 里？

**A**: 按链路排查（每一步都有日志）：

```bash
# 1. 拉取日志（服务器 → Mac 的会话拉到了吗）
tail -50 ~/.hermes/logs/mac-session-pull.log

# 2. 导出（会话 → Raw md）
bash ~/ai-obsidian-auto/scripts/export-all.sh

# 3. 看 Raw 文件有没有
ls ~/obsidian/*/Chat\ Logs/2026/
```

哪一步断了修哪一步。最常见：免密失效（重做第 4 步）、Mac 关机（开机就好，不会丢数据）。

### Q: Wiki 一直不更新（蒸馏不跑）？

**A**:

```bash
# 看蒸馏日志
journalctl --user -u obsidian-server-distill --since "6h" --no-pager | tail -40

# 手动触发一次
systemctl --user start obsidian-server-distill.service
```

常见原因：蒸馏 provider 的 API key 失效/额度耗尽（日志会显示 `API call failed`，fallback 链会尝试降级）；或 Raw 没有新文件（蒸馏是增量的，没新聊天就不跑）。

### Q: Mac 关机了会怎样？

**A**: 什么都不丢。服务器拉不到会话（但关机时本来也不产生会话），其他一切照常。Mac 开机后下次拉取周期自动补上。

### Q: 换新 Mac 怎么办？

**A**: 见 [join-flow.md](join-flow.md)——6 分钟重新加入，服务器自动接管。

### Q: 微信 Bot 发消息没反应？

**A**: 依次检查：

```bash
# 1. 网关服务是否 active
systemctl --user status hermes-gateway-wechat2

# 2. 日志（最常见：token 过期要重新扫码）
journalctl --user -u hermes-gateway-wechat2 --since "30 min" --no-pager | tail -20

# 3. 重启试试
systemctl --user restart hermes-gateway-wechat2
```

### Q: 微信会不会封号？

**A**: 微信官方没有开放 Bot API，iLink 是第三方协议实现，**存在账号风控风险**。实践建议：用**小号**跑网关（主号只负责日常聊天），发送频率控制在 2 秒/条以上。详见 [gateway.md](gateway.md)。

### Q: Telegram 连不上（国内网络）？

**A**: 需要代理。Telegram 服务器在海外，国内网络需要代理才能连接；具体见 [deployment.md](deployment.md) 的网关章节。

## 进阶

### Q: 我想加一个新的 AI 客户端（比如 Cursor / Gemini CLI）？

**A**: 见 [client-onboarding.md](client-onboarding.md)。约需改 3 处，30 分钟内搞定。

### Q: 怎么让微信/Telegram 聊天也沉淀？

**A**: 需要 Hermes Gateway（消息平台接入层），见 [AI-CLIENTS.md](AI-CLIENTS.md) 第 5 节。这是可选的高级功能。

### Q: 蒸馏出来的知识质量不满意？

**A**: 蒸馏 prompt 在 `ai_chat_unified_distill_cron.sh` 里，可以自己调：

- 想更保守（只留高价值结论）→ 在 prompt 里强调过滤
- 想更多细节 → 放宽过滤条件
- 换更强的蒸馏模型 → 改 `.env` 的 `AI_DISTILL_MODEL`

### Q: 我想把数据备份到网盘？

**A**: 支持 rclone 加密备份，见 [deployment.md](deployment.md) 备份章节 + [security.md](security.md) 备份策略。
