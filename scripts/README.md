# scripts/ — 核心脚本

> 所有脚本已**脱敏** + **环境变量驱动**：不再硬编码任何路径/IP/用户名，统一从 `.env` 读取。
> 配置方式：复制根目录 `.env.example` 为 `.env`，填入你的值。

## 配置（唯一来源：.env）

```bash
cp .env.example .env
vim .env   # 填入 OBSIDIAN_VAULT_PATH / PRIMARY_MAC_IP / SSH_USER 等
```

各脚本消费的变量（与 .env 一一对应，无需额外映射）：

| 变量 | 用途 | 消费脚本 |
|------|------|----------|
| `OBSIDIAN_VAULT_PATH` | 服务器 vault 路径 | 全部 |
| `HERMES_HOME` | Hermes 数据目录 | 蒸馏/索引/自愈/导出 |
| `PRIMARY_MAC_IP` | 主 Mac IP | vault-pull / mac-session-pull |
| `SSH_USER` | 主 Mac SSH 登录名 | vault-pull / mac-session-pull |
| `MAC_USER` | 主 Mac 本地用户名（iCloud 路径） | vault-pull |
| `AI_DISTILL_PROVIDER` / `AI_DISTILL_MODEL` | 蒸馏主模型 | server-wiki-distill |
| `DEEPSEEK_API_KEY` / `KIMI_API_KEY` | fallback 链 key | ai_chat_unified_distill |

## 脚本说明

### 拉取层（服务器主动拉）

| 脚本 | 职责 |
|------|------|
| `vault-pull.sh` | 拉主 Mac iCloud Vault（手动编辑 + 注册标记） |
| `mac-session-pull.sh` | 拉所有已加入 Mac 的 AI 会话（Claude/Codex/Pi/DSH） |
| `node-discovery.sh` | 扫描 `.hermes-nodes/` 注册标记，自动发现新机器 |

### 导出层

| 脚本 | 职责 |
|------|------|
| `export-all.sh` | 导出入口（Claude/Pi/DSH + Codex），crontab 每小时调度 |
| `ai_chat_export.py` | 统一导出器：Claude/Pi/DSH 会话 → Raw Chat Logs MD |

### 蒸馏/入库层

| 脚本 | 职责 |
|------|------|
| `server-wiki-distill.sh` | 蒸馏 service 入口 |
| `ai_chat_unified_distill_cron.sh` | 统一蒸馏（Raw → Wiki/Lessons，含 fallback 链） |
| `wiki_ingest.py` | URL / 文件 / 文本入库 |

### 索引层

| 脚本 | 职责 |
|------|------|
| `obsidian_backup.py` | SQLite FTS5（全库）+ Chroma（Wiki 高信号层） |
| `obsidian_cron.sh` | 增量索引入口 |
| `server-wiki-chroma.sh` | Chroma 重建 service 入口（被 obsidian-server-chroma.timer 每周调度） |

### 备份/自愈层

| 脚本 | 职责 |
|------|------|
| `wiki_git_autocommit.sh` | Wiki 知识层 Git 自动提交推送 |
| `hermes-self-heal.sh` | Hermes 代码目录自愈 |
| `redact_secrets.py` | 敏感信息识别 + Keychain 加密替换 |

### 部署

| 脚本 | 职责 |
|------|------|
| `setup-server.sh` | 一键部署：建目录 + 生成 systemd units + 启用 timer + crontab |

## 依赖

```bash
python3 -m venv ~/.hermes/obsidian-backup-env
~/.hermes/obsidian-backup-env/bin/pip install zstandard chromadb
```

## 注意事项

1. `ai_chat_export.py` 的 `default_vault()`：Linux 上回退 `~/obsidian`（不是 Mac iCloud 路径）
2. 蒸馏脚本的 manifest 与 state 两处 `for root in (...)` 都要包含全部 `*/Chat Logs` 目录
3. `hermes-self-heal.sh` 是 Hermes 专属，非 Hermes 用户可忽略
