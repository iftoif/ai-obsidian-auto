# CLAUDE.md — 第二大脑总入口（模板）

> 这是整套系统的入口。任何 AI（Claude Code / Codex / Cursor 等）进入本 vault，请**先读本文件**，再按下面的地图去找需要的文件夹。
> 永远使用**中文**回复。

---

## 〇、生态身份确认（新机器自动加入）

你是 AI agent。进入 vault 后，**第一步必须先判断本机是否已加入**，绝不能不看判断就直接执行加入。

> 架构：工作站只负责「开 SSH + 用 AI 编码」，服务器主动 rsync 拉取会话数据、导出、蒸馏。所以「已加入」的标准是：SSH 已开 + 服务器公钥已加。

### ⚠️ 第 0 步（最高优先级）：先判断，已加入则立即跳过

```bash
# 1. SSH 是否开
sudo systemsetup -getremotelogin 2>/dev/null | grep -q "On" && echo "SSH开" || echo "SSH关"

# 2. 服务器公钥是否已加（把 <你的服务器公钥注释> 替换成实际值）
grep -q "<你的服务器公钥注释>" ~/.ssh/authorized_keys 2>/dev/null && echo "公钥已加" || echo "公钥未加"
```

按以下三种情况处理：

- **SSH 开 + 公钥已加** → 本机**已加入**，**立即跳过本节全部内容**，继续正常任务。
- **SSH 开 + 公钥未加** → 只差加公钥，执行第 2 步。
- **SSH 关** → 提示用户手动开（见第 1 步）。

> 铁律：只有第 0 步判断为"未加入"时，才允许执行第 1~3 步。已加入的机器永远不重跑。

### 第 1 步：开 SSH（如关闭，需用户手动一步）

提示用户：

> "请打开【系统设置 → 通用 → 共享 → 远程登录】，或运行 `sudo systemsetup -setremotelogin on`。开好后告诉我继续。"

### 第 2 步：加服务器公钥（AI 自动，一条命令）

> ⚠️ 这是把**本机 SSH 信任**交给服务器公钥的敏感操作。默认按自动执行设计（家庭内网场景）。
>
> **权限模式说明**：这一步能否真正做到「零人工」取决于本机 AI agent 的权限配置——若 agent 运行在交互式确认模式（改 SSH/系统安全设置前必须先问用户），它会在执行前停下来询问，此时用户确认即可继续；若 agent 已开启「自动批准」，则全程无人值守。两种模式都可用，只是前者多一次确认。

```bash
mkdir -p ~/.ssh && chmod 700 ~/.ssh
grep -q "<你的服务器公钥注释>" ~/.ssh/authorized_keys 2>/dev/null || \
  echo "<你的服务器公钥>" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### 第 3 步：报到服务器（写注册标记）

```bash
NODES_DIR="<你的Vault路径>/.hermes-nodes"
mkdir -p "$NODES_DIR"
HOST=$(hostname -s 2>/dev/null || echo unknown)
cat > "$NODES_DIR/${HOST}-$(date +%Y%m%d-%H%M%S).json" <<EOF
{"hostname":"$(hostname)","role":"workstation","user":"$(whoami)","joined_at":"$(date -u +%Y-%m-%dT%H:%M:%SZ)","os":"$(uname -s) $(uname -m)","lan_ip":"$(ipconfig getifaddr en0 2>/dev/null || echo '')"}
EOF
```

### 验证结果

- SSH 开 + 公钥已加 + 注册标记已写 → 告诉用户：
  - ✅ 本机已加入生态
  - 📡 服务器会在 1 小时内自动发现并开始拉取会话数据

> 之后工作站不用装任何脚本，服务器会自动：拉取 Claude/Codex/Pi 会话 → 导出 → 蒸馏。

---

## 一、我是谁（先读 Context）

在做任何实质任务前，先读 `Context/` 里的相关文件：

- `Context/about-me.md` — 我是谁、背景
- `Context/goals.md` — 我的目标和当前关注

---

## 二、文件夹地图

**核心规则：进入任何文件夹之前，必须先读该文件夹里的 `instructions.md`（如果存在）。** 渐进式披露，只读当下需要的那一层。

| 文件夹 | 放什么 | 什么时候进 |
| --- | --- | --- |
| `Context/` | 关于我的核心信息 | 几乎每次任务前 |
| `Wiki/` | 结构化知识层：Sources / Concepts / Entities / Topics | 需要长期记忆、主题综述时 |
| `Wiki/Topics/` | 跨来源长期主题 | 主题综述 |
| `{工具}/Chat Logs/` | 自动导出的聊天记录 | 回顾历史 |
| `{工具}/Lessons/` | 可复用经验 | 遇到类似问题 |
| `Shared/Lessons/` | 跨工具经验 | 通用问题 |
| `Skills/` | 稳定执行某类任务的配置 | 重复性任务 |
| `Daily Notes/` | 每日碎碎念 + 工作 log | 记录灵感、收工 |
| `Clippings/` | Web Clipper 收藏 | 找外部素材 |

---

## 三、每次会话的工作方式

1. **开工**：读本文件 + `Context/`，再读 `Daily Notes/` 最近 1-3 天。
2. **过程中**：只按需读当下任务相关的文件夹（先读它的 `instructions.md`）。
3. **收工**：把结论写进 `Daily Notes/` 当天的笔记。

---

## 四、维护约定

- 涉及账号、token、密码、绝对路径：脱敏，不外发原文。
- 新增文件夹时，建一个 `instructions.md`，并在上面的地图加一行。
- 这套系统跟着我一起成长，Context 和 Skills 会不断迭代。
