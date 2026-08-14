# templates/systemd/ — systemd user units 模板

> ⚠️ **推荐用 `setup-server.sh` 自动生成 unit**（它会写入正确的仓库路径 + 环境变量注入）。
> 本目录的模板仅供：1) 理解 unit 结构 2) 手工定制部署。手工使用时必须自己替换路径。

## 手工部署注意（重要）

模板里 `ExecStart=%h/.hermes/scripts/xxx.sh` 是**示例占位**——第十一轮起脚本不再拷贝到
`~/.hermes/scripts/`，而是直接从**仓库路径**运行。手工部署请把每个 service 的 ExecStart 改为：

```ini
ExecStart=/home/<你的用户>/ai-obsidian-auto/scripts/mac-session-pull.sh
```

（即你的仓库 clone 目录下的 scripts/ 绝对路径。）

## 安装

```bash
mkdir -p ~/.config/systemd/user
cp templates/systemd/*.service templates/systemd/*.timer ~/.config/systemd/user/
# ↑ 复制后必须逐个编辑 ExecStart 改成你的仓库路径（见上）

loginctl enable-linger $USER   # 无登录会话时定时器也运行

# 核心：拉取 + 蒸馏 + 索引 + Git + Chroma
systemctl --user enable --now mac-session-pull.timer vault-pull.timer
systemctl --user enable --now obsidian-server-distill.timer obsidian-server-index.timer
systemctl --user enable --now wiki-git-autocommit.timer obsidian-server-chroma.timer

# 可选：自动发现 + 自愈
systemctl --user enable --now node-discovery.timer hermes-self-heal.timer
```

## 单元说明

| 单元 | 频率 | 说明 |
|------|------|------|
| mac-session-pull.timer | 每小时 | 拉所有 Mac 的 AI 客户端会话 |
| vault-pull.timer | 每小时 | 拉主 Mac iCloud Vault |
| node-discovery.timer | 每小时 | 自动发现新机器 |
| hermes-self-heal.timer | 每小时 | Hermes 代码自愈 |
| obsidian-server-index.timer | 每小时 | SQLite FTS5 索引 |
| obsidian-server-distill.timer | 每 4h | LLM 蒸馏 |
| wiki-git-autocommit.timer | 每小时 | Wiki Git 提交 |
| obsidian-server-chroma.timer | 每周日 | Chroma 语义索引重建 |

## 依赖

- 脚本从仓库 `scripts/` 目录运行（git pull 更新立即生效），unit 的 ExecStart 必须指向它
- 蒸馏 service 需 secret store EnvironmentFile（见 ../../docs/deployment.md）
