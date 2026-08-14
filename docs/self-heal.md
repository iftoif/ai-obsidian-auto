# 自愈机制

四套机制协同，覆盖"重装/换目录/新机器"场景。

## 1. 服务器自愈（hermes-self-heal）

- 每小时检测服务器 Hermes 代码目录
- 缺失时自动发现新目录（软链接 → command -v → 扫描候选）
- 自动重绑：软链接 + systemd + 重放 patch
- 用系统 Python（不依赖 hermes，避免自己也断）

## 2. 节点发现（node-discovery）

- 每小时扫描 Vault 注册标记
- 发现新机器自动：SSH 信任 + 节点文档 + 通知
- 幂等：已登记节点跳过

## 3. 新机器身份确认（CLAUDE.md）

AI 进入 Vault 读 CLAUDE.md，判断三态：
- SSH 开 + 公钥加 → 已加入，跳过
- SSH 开 + 公钥未加 → 加公钥 + 报到
- SSH 关 → 提示用户开远程登录

## 4. 客户端换目录自动发现

导出脚本自动发现客户端数据目录：
1. 环境变量（CLAUDE_CONFIG_DIR / CODEX_HOME / PI_HOME）
2. 默认位置（~/.claude 等）
3. 扫描 home 下所有一级目录，识别特征子目录

## 完整自愈链路

```txt
服务器 Hermes 重装 → self-heal 自动重绑
客户端换目录 → 导出脚本自动发现
Hermes 升级 → patch 自动重放
新机器 → CLAUDE.md 身份确认 + join
```

## 设计原则

- 幂等：已处理的不重复
- 降级：找不到就告警，不破坏现状
- 独立：各机制互不依赖，一个挂了不影响其他
