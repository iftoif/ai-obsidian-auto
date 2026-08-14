# templates/systemd/ — systemd user units 模板

> 复制到服务器 ~/.config/systemd/user/ 后使用。所有路径已用 %h（用户家目录）替代真实路径。
> 需要 Hermes Gateway 的服务（hermes-self-heal / node-discovery）按需启用。

## 安装

```bash
mkdir -p ~/.config/systemd/user
cp templates/systemd/*.service templates/systemd/*.timer ~/.config/systemd/user/

# 核心：拉取 + 蒸馏 + 索引 + Git
systemctl --user enable --now mac-session-pull.timer vault-pull.timer
systemctl --user enable --now obsidian-server-distill.timer obsidian-server-index.timer
systemctl --user enable --now wiki-git-autocommit.timer

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

- 蒸馏/索引/拉取脚本需在 ~/.hermes/scripts/（见 ../../scripts/）
- 蒸馏 service 需 secret store EnvironmentFile（见 ../../docs/deployment.md §3.1）
