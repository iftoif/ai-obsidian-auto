# 新机器加入流程

新机器拿到手，最快 6 分钟加入，之后全自动。

## 第 1 步：初始化 + 登录 iCloud（3 分钟）

1. 开机初始化，登录 Apple ID（iCloud 同步 Obsidian Vault）
2. 等 Vault 同步完成（本机出现 CLAUDE.md）

## 第 2 步：装 AI 客户端（2 分钟）

```bash
npm install -g @anthropic-ai/claude-code   # Claude Code
npm install -g @openai/codex               # Codex（可选）
```

## 第 3 步：开 SSH（30 秒）

系统设置 → 通用 → 共享 → 打开「远程登录」

> 这是"给服务器权限"，服务器靠 SSH 拉取会话数据。

## 第 4 步：加服务器公钥 + 报到（AI 自动）

在 Vault 目录打开 Claude Code，说「读 CLAUDE.md，帮我加入生态」：

```txt
AI 自动：
1. 判断 SSH 已开 + 公钥未加
2. 加服务器公钥到 ~/.ssh/authorized_keys
3. 写注册标记（含主机名/用户名/IP）到 Vault/.hermes-nodes/
```

## 第 5 步：服务器自动接管（零操作）

```txt
node-discovery（每小时）→ 发现注册标记 → 通知你
mac-session-pull（每小时）→ SSH 拉取会话
蒸馏（每 4h）→ 会话 → Wiki/Lessons
索引 + 备份 → 各自定时
```

## 验证成功

- ✅ 收到通知「新机器加入生态」
- ✅ 服务器出现「节点-xxx.md」
- ✅ 之后聊天自动进知识库

## 注意

- Mac 关机时服务器拉不到（但也不产生会话，无影响）
- 换机器/重装：重做第 1~4 步，服务器自动重新接管
- 注册标记必须含 user 字段（服务器靠它识别 SSH 用户名）
