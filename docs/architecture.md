# 架构

> 本文基于一套在真实环境中运行的系统整理（2026-08 实测）。所有 IP / 用户名 / 路径已脱敏为占位符。

## 0. 一句话

**多 Agent（Claude Code / Codex / Pi / Hermes / DSH）→ 各工具 Raw Chat Logs → 统一导出 → LLM 蒸馏 → Wiki/Lessons 沉淀（Obsidian vault）→ 双索引（SQLite FTS5 + ChromaDB）→ 多机同步 + Git + 加密备份。**

## 1. 拓扑

```text
┌─────────────── 服务器（核心，7×24）───────────────┐
│  消息：微信 ×N + Telegram（Hermes Gateway）       │
│  蒸馏：AI_DISTILL_MODEL → Wiki/Lessons（fallback 链） │
│  索引：SQLite FTS5 每小时 + Chroma 每周           │
│  备份：Git 每小时 + 加密备份 每日                 │
│  拉取：每小时 SSH 拉所有 Mac 会话 + iCloud Vault  │
└──────────────────┬──────────────────────────────┘
                   │ 双向同步（每 4h，不带 --delete）
┌──────────────────┴──────────────────────────────┐
│  iCloud Vault（Obsidian 编辑入口，唯一主源）     │
└─────────────────────────────────────────────────┘

┌─────────────── Mac（工作站，按需）────────────────┐
│  Claude Code / Codex / Pi / DSH（交互式编码）     │
│  Hermes Desktop（本地对话）                       │
│  ↓ 只需开 SSH，服务器主动拉取会话                │
└─────────────────────────────────────────────────┘
```

## 2. 各层职责

| 层 | 职责 | 载体 |
|---|---|---|
| **输入层** | 消息平台网关（微信/Telegram） | Hermes Gateway（服务器） |
| **Raw 层** | 原始会话证据，只读 | `Hermes/Chat Logs/`、`Codex/Chat Logs/`、`Claude/Chat Logs/`、`Pi/Chat Logs/`、`DSH/Chat Logs/`、`简报/` |
| **Wiki 层** | AI 增量维护的结构化理解 | `Wiki/Sources/`、`Wiki/Concepts/`、`Wiki/Entities/`、`Wiki/Topics/` + 各工具 `Lessons/` |
| **Schema 层** | 规则、索引、变更日志 | `CLAUDE.md`、`Wiki/AGENTS.md`、`Wiki/Index.md`、`Wiki/Log.md`、各目录 `instructions.md` |
| **索引层** | 检索 | SQLite FTS5（全库）+ ChromaDB（Wiki 高信号层 chunk 级） |
| **备份层** | 版本控制 + 加密备份 | Git 每小时、加密备份每日 |

## 3. 自动化定时器

### 服务器 systemd user timers

| 定时器 | 频率 | 职责 |
|---|---|---|
| `mac-session-pull.timer` | 每小时 | 遍历 `.hermes-nodes/` 注册标记，SSH 拉所有 Mac 的 Claude/Codex/Pi/DSH 会话 |
| `vault-pull.timer` | 每小时 | 拉主 Mac iCloud Vault（手动编辑 + 注册标记） |
| `node-discovery.timer` | 每小时 | 扫描注册标记发现新机器，自动 SSH 信任 + 通知 |
| `hermes-self-heal.timer` | 每小时 | 检测 Hermes 代码目录，缺失自动重绑 |
| `obsidian-server-index.timer` | 每小时 | SQLite FTS5 增量索引 |
| `obsidian-server-distill.timer` | 每 4h | LLM 蒸馏：Raw → Wiki/Lessons |
| `wiki-git-autocommit.timer` | 每小时 | 知识层 Git 提交推送 |
| `obsidian-server-chroma.timer` | 每周日 | ChromaDB 高信号层重建 |
| `obsidian-rclone-backup.timer` | 每日 | 加密备份（vault/database/runtime） |

### 服务器 crontab（导出）

```cron
0 * * * *  chat_export_cron.sh        # Hermes 微信/Telegram 日志导出
3 * * * *  ai_chat_export_cron.sh     # Claude/Pi/DSH 会话导出
7 * * * *  codex_chat_export_cron.sh  # Codex 会话导出
```

## 4. 蒸馏管道

### 输入

- 各工具 Raw Chat Logs（统一格式：frontmatter + `## HH:MM:SS 用户/助手` 逐轮时间戳；>2MB 滚动 `-02.md`；图片落盘 assets 并写 `![[assets/xxx.jpg]]` 引用）

### 处理

1. 扫描新增/修改的 Raw 文件（按 mtime+size 签名增量）
2. 读取文件 + 用 vision 读图
3. LLM 按 prompt 蒸馏：过滤寒暄/工具输出/调试过程，保留结论、决策、踩坑、可复用经验
4. 写入：新建/更新 `Wiki/Sources/日期-摘要.md`；按工具写 `Lessons/`；跨工具写 `Shared/Lessons/`；已有主题增量合并
5. 冲突处理：新旧结论**并列保留**，各自标注来源/时间/失效原因，不覆盖旧结论
6. 同步维护 Index 与 Log

### Provider 降级链

```text
主：your-provider / your-model
降级：fallback 链（如 deepseek → kimi）
失败检测：基于输出内容（hermes chat 失败退出码可能为 0）
```

## 5. 关键机制

### 双向同步（非单向 --delete）

```text
方向1：服务器 → iCloud（蒸馏产物 + 微信日志回传）
方向2：iCloud → 服务器（手动编辑 + Mac 客户端会话）
不带 --delete，避免误删任一端的蒸馏产物
```

### 多机加入（注册制）

1. 新 Mac 开 SSH + 加服务器公钥
2. 写注册标记 `.hermes-nodes/<hostname>-<ts>.json`（含 user/lan_ip/role）
3. 服务器 `node-discovery` 发现 → 自动 SSH 信任 → 通知
4. 服务器 `mac-session-pull` 按标记拉取（`test -d` 容错：未装某客户端的机器自动跳过）

### 自愈

- Hermes 升级会覆盖源码 → `hermes_patch.py` 自动重放 3 个补丁（图片保留 / 静默 shutdown / systemd EnvironmentFile）
- 服务器 Hermes 代码目录缺失 → `hermes-self-heal` 每小时重绑

## 6. 图片管线

```text
微信图片 → cache/images（软链）→ assets/weixin/
→ vision（glm-4v-flash）预分析
→ chat_export.py 生成 ![[assets/weixin/xxx.jpg]]
→ 双向同步 → Obsidian 可见 → 蒸馏（luna vision）读图
```

## 7. 数据规模参考（真实）

- Vault：约 400+ Markdown，140MB
- SQLite FTS5：约 300MB
- 会话拉取：Codex 单机 550MB+，Claude 数十 MB，Pi 12MB+
- 单次蒸馏：读十几份 Raw，产出数页 Wiki

## 8. 已知边界与演进方向

- **新增客户端 = 3 处适配**（拉取目录 / 导出器 / 格式验证），目前无插件化注册机制
- 蒸馏依赖外部 LLM API，有 provider 降级链兜底，但离线不可用
- ChromaDB 只索引 Wiki 高信号层，长 Raw 日志走 FTS5
- 下一步候选：新客户端注册插件化、蒸馏分块策略、语义索引升级为 Wiki 优先 chunk 级
