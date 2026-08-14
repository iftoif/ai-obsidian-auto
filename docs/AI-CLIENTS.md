# AI 客户端安装与配置清单

> 本套系统的「输入」来自各 AI 客户端的会话记录。
>
> **所有客户端都是可选的**：用哪个装哪个，不用的不装；系统按「目录存在才拉取」容错设计，只装一个也能跑。唯一的硬依赖是第 4 节的「蒸馏用 LLM」。

## 1. Claude Code（Anthropic）（可选）

```bash
# 安装
npm install -g @anthropic-ai/claude-code

# 登录（订阅账号或 API key）
claude
# 首次启动会引导登录，支持：
#   - Claude 订阅账号（OAuth 登录）
#   - Anthropic API key（env: ANTHROPIC_API_KEY）
```

会话数据目录：`~/.claude/projects/`（系统自动拉取）

## 2. OpenAI Codex（可选）

```bash
# 安装
npm install -g @openai/codex

# 登录（ChatGPT 订阅账号）
codex
# 或设置 API key：env: OPENAI_API_KEY

# 登录 Codex 订阅
codex login
```

会话数据目录：`~/.codex/sessions/`（系统自动拉取）

## 3. Pi（Nous Research）（可选）

```bash
# 安装
npm install -g @voussoir/pi

# 登录（需要账号）
pi setup
```

会话数据目录：`~/.pi/agent/sessions/`（系统自动拉取）

## 3.5 DeepSeek Harness（DSH）（可选）

本项目作者在用的 AI 编程环境（DeepSeek Harness），已内置接入。

- 会话数据目录：`~/.dsh/sessions/`（zstd 压缩 jsonl，系统自动拉取）
- 接入方式：已在 `mac-session-pull.sh` + `ai_chat_export.py` 内置（含插件注入消息过滤）
- 无需额外配置；如果你也用 DSH，装好后自动沉淀

> 接入 DSH 的完整实战记录见 [client-onboarding.md](client-onboarding.md)。

## 4. 蒸馏用 LLM（必须至少配一个）

蒸馏把 Raw 聊天记录变成结构化知识，需要一个可调用的 LLM。

### 方案 A：Hermes 内置 provider

```bash
# 安装 Hermes（如果还没装）
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash

# 配置蒸馏 provider（改 ~/.hermes/config.yaml 或环境变量）
# 支持：openai-codex（ChatGPT 订阅）、zai、deepseek、kimi、anthropic 等
```

### 方案 B：直接用 API key

创建 `~/.config/hermes/secret-store/hermes.env`（权限 600）：

```bash
# 任选一个你有 key 的（替换成你的真实 key，此文件已被 gitignore 排除）
DEEPSEEK_API_KEY=<你的deepseek-key>
# 或
KIMI_API_KEY=<你的kimi-key>
# 或
GLM_API_KEY=<你的glm-key>
```

> 推荐配置降级链：主模型 + 1~2 个兜底 provider，额度耗尽自动降级，蒸馏不断（见 .env.example 的 FALLBACK_* 配置）。

## 5. ⭐ 消息网关（Hermes Gateway）—— 本系统最大价值

> **建议第一个装。** 让手机变成 AI 指挥台 + 聊天自动沉淀 + 定时简报推送。
>
> 完整介绍（是什么 / 为什么先装 / 能做什么 / 微信 vs Telegram 选型 / 踩坑）见 [gateway.md](gateway.md)。

快速开始：

```bash
# 微信网关（每个微信账号一个 gateway）
hermes gateway add wechat --profile wechat2
systemctl --user start hermes-gateway-wechat2   # 扫码登录

# Telegram 网关（官方 Bot API）
# @BotFather 创建 Bot 拿 token → 配置 TELEGRAM_BOT_TOKEN → 启动
systemctl --user start hermes-gateway
```

## 6. 验证是否可用

```bash
# 检查各客户端已产生会话（说明在用）
ls ~/.claude/projects/ 2>/dev/null | head -3
ls ~/.codex/sessions/ 2>/dev/null | head -3

# 检查蒸馏模型可调用
hermes chat --provider <你的provider> -m <你的model> -q "测试" 2>&1 | tail -2
```

## 新增一个 AI 客户端？

见 [docs/client-onboarding.md](docs/client-onboarding.md) —— 按清单接入约需改 3 处。
