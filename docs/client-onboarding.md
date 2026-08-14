# 新增 AI 客户端接入清单

> 把一个全新的 AI 客户端（如 Gemini CLI / Cursor / 新 Agent）接入这套生态，让它像 Claude Code / Codex / Pi / Hermes / DSH 一样：会话被拉取 → 导出 → 蒸馏 → 沉淀进 Wiki/Lessons。

## 核心结论

**每新增一个 AI 客户端，要在 3 处加适配**：拉取、导出、蒸馏消费。其中前两处必须动手，蒸馏层只认统一 Raw 格式，通常不用改。

## 三层接入点

### 1. 会话拉取（服务器 mac-session-pull.sh）

服务器每小时主动 SSH 拉取所有已加入 Mac 的会话数据。目前**写死了 4 个目录**：

- `~/.claude/projects`
- `~/.codex/sessions`
- `~/.pi/agent/sessions`
- `~/.dsh/sessions`

新客户端要手动加一段：

```bash
# 在 pull_node() 里追加（示例）
if ssh -o BatchMode=yes "$user@$ip" "test -d ~/.新客户端" 2>/dev/null; then
  rsync -avz "$user@$ip:~/.新客户端/" "$HOME/.新客户端/" 2>&1 | tail -1
  echo "  ✅ 新客户端会话已拉取"
fi
```

容错设计：`test -d` 不存在就跳过（避免 rsync error 23），所以不装该客户端的机器不受影响。

### 2. 原始导出（服务器 ai_chat_export.py）

- 每个客户端一个 `xxx_records()` 生成器 + 在 `export_tool()` 注册分发
- 已注册：`claude_records()`、`pi_records()`、`dsh_records()`；Codex 走独立 `codex_chat_export_cron.sh`；Hermes 走 `chat_export.py` + profiles
- 新客户端：写 `xxx_records()`（解析它的 session 格式 → 统一 Raw Markdown），在 `export_tool()` 加一行分发
- **目录解析已自动放宽**：`_resolve_client_dir()` 支持 环境变量 → 默认位置 → 候选扫描 三级，换目录不用改代码

#### records 生成器契约

```python
# 每个记录 yield：(源文件, 行号, 时间戳, 角色, 文本, session_id, cwd)
def xxx_records(home: Path) -> Iterable[tuple[Path, int, dt.datetime, str, str, str, str]]:
    ...
    yield path, line_no, ts, role, text, session, cwd
```

### 3. 蒸馏消费（统一 Raw 格式，无需改）

distiller 只认统一 Raw Markdown：

- frontmatter（source/type/date/tags）
- `## HH:MM:SS 用户/助手` 逐轮时间戳
- >2MB 滚动 `-02.md`
- 图片落盘 assets 并写 `![[assets/xxx.jpg]]` 引用
- 写入前过 redact_secrets.py 脱敏

**新客户端只要导出成这个格式，蒸馏自动识别**。这是「exporter 翻译、distiller 只认统一格式」架构的收益。

## 接入步骤（新增客户端 X）

1. 服务器 `mac-session-pull.sh`：加目录检测 + rsync（见上）
2. `ai_chat_export.py`：写 `x_records()` + 注册 `export_tool()`；有图片要落盘则参考 `_iter_images_from_content`（兼容不同内嵌格式）
3. 蒸馏目录清单：`ai_chat_unified_distill_cron.sh` 里 manifest 与 state 两处 `for root in (...)` 加 `X/Chat Logs`
4. 验证：
   - `bash -n` / `python3 -m py_compile` 语法检查
   - 服务器真实跑一次导出，确认 Chat Logs 生成、字段齐全
   - `ai_chat_unified_distill_cron.sh --dry-run` 确认 manifest 含新文件
   - 有图片时确认落盘 + Obsidian 可见
5. 更新 `Shared/Index.md` 加链接；必要时在 `Wiki/Entities/` 建实体页

## 放宽路径（不是所有客户端都要全改）

| 场景 | 要改什么 |
|---|---|
| 同客户端换目录 | 不用改（环境变量/默认/候选三级自动发现） |
| 新客户端复用既有格式目录（如 ~/.codex/sessions） | 拉取白嫖，只需导出器认识格式 |
| 只本地交互、不上链 | 什么都不用加（目录不存在自动跳过） |
| 全新 session 格式 + 新目录 | 3 处全改（拉取 + 导出 + 格式验证） |

## 实战案例：接入 DSH（DeepSeek Harness）

DSH 是一个全新的客户端（zstd 压缩 jsonl 会话），按清单全量接入，是「全新 session 格式 + 新目录」档的完整示例：

### 会话格式

- 路径：`~/.dsh/sessions/<cwd-hash>/session-<id>/session.jsonl.zstd`
- 压缩：zstd（需 `zstandard` 库流式解压，文件无 content size 头，不能一次性 decompress）
- 核心行类型：
  - `session` → {id, cwd, createdAt}
  - `user/message` → {time, data:{content, role, source}}
  - `assistant/message` → {time, data:{turn, step, message:{role, content}}}
- 其余（reasoning-chunks / assistant/chunk / tool-call-chunks / text-chunks / step/start…）都是流式过程事件，跳过

### 两个必须处理的坑

1. **插件注入过滤**：DSH 会把 runtime context / system-reminder / policy 快照以 `user/message` 形式注入（`data.source.kind: plugin`）。必须只保留 `kind: user` 的真实输入，否则 Raw 会被系统提示污染：

```python
src = d.get("source") if isinstance(d.get("source"), dict) else {}
if role == "user" and src.get("kind") not in (None, "user"):
    continue
```

2. **content 元素过滤**：`assistant/message` 的 content 含 `reasoning` / `tool-call` / `tool-result`，只保留 `type: text`：

```python
if item.get("type") != "text":
    continue
```

### 接入结果（实测）

- 干净重放：79 条消息（9 真实用户 + 70 助手），插件噪音 0
- 蒸馏 dry-run：manifest 自动包含 `DSH/Chat Logs/2026/2026-08-14.md`
- 调度：crontab 的 `ai_chat_export_cron.sh`（--tool all）自动覆盖 DSH

## 未来方向

- 把「拉取目录 + 导出器」注册制改为插件化（声明式 manifest：目录/格式/导出器路径），新增客户端只需放一个目录
- 提供 `validate_client()` 校验脚本：一键检查拉取、导出、蒸馏三环节
