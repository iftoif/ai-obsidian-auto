# 文档导航

> 按阅读顺序推荐，从「这是什么」到「怎么跑起来」。

## 快速开始（新手路径）

| 顺序 | 文档 | 内容 | 适合谁 |
|---|---|---|---|
| 0 | [quickstart.md](quickstart.md) | **保姆级教程**：从零跑通，每一步有解释 | 第一次来，想直接装 |
| 1 | [faq.md](faq.md) | 常见问题（装前/装中/装后/进阶） | 卡住了 |
| 2 | [gateway.md](gateway.md) | **消息网关**：手机指挥 AI + 微信 vs Telegram 选型 | 装网关（强烈推荐） |
| 3 | [AI-CLIENTS.md](AI-CLIENTS.md) | 前置条件：AI 客户端安装与登录 | 装 AI 工具时 |
| 4 | [architecture.md](architecture.md) | 完整架构与真实链路 | 想理解原理 |
| 5 | [vault-structure.md](vault-structure.md) | 知识库目录结构 | 想理解知识层 |
| 6 | [deployment.md](deployment.md) | 部署手册（深入版） | 自定义部署 |
| 7 | [join-flow.md](join-flow.md) | 新机器 6 分钟加入流程 | 换 Mac |

## 按主题查阅

### 入门

- [quickstart.md](quickstart.md) — 保姆级从零教程（每步解释 + 验证点）
- [gateway.md](gateway.md) — **消息网关详解**：是什么 / 为什么先装 / 能做什么 / 微信 vs Telegram 选型 / 踩坑
- [faq.md](faq.md) — 常见问题与排障
- [AI-CLIENTS.md](AI-CLIENTS.md) — AI 客户端安装与配置、蒸馏用 LLM 配置

### 架构与设计

- [architecture.md](architecture.md) — 系统总览、真实链路、数据规模参考
- [knowledge-layer.md](knowledge-layer.md) — Raw-Wiki-Schema 三层知识库设计 + 维护规则
- [vault-structure.md](vault-structure.md) — Vault 目录结构与渐进式披露

### 部署与运维

- [deployment.md](deployment.md) — 部署手册、排障速查、常见坑
- [join-flow.md](join-flow.md) — 新机器加入流程
- [self-heal.md](self-heal.md) — 四套自愈机制（重装/换目录/新机器）

### 数据管线

- [distill-pipeline.md](distill-pipeline.md) — 蒸馏管道：增量机制、规则、fallback 链、图片处理
- [client-onboarding.md](client-onboarding.md) — 新增 AI 客户端接入清单（含 DSH 实战案例）

### 安全

- [security.md](security.md) — 威胁模型、脱敏管线、密钥管理、自检清单

## 文档关系图

```text
quickstart.md（小白从零开始）
  ├── gateway.md（★ 先装网关：手机指挥 AI）
  └── faq.md（卡住看这里）
architecture.md（总览）
  ├── vault-structure.md      —— 知识库长什么样
  ├── knowledge-layer.md      —— 三层架构设计哲学
  ├── distill-pipeline.md     —— 数据怎么流转
  ├── deployment.md           —— 怎么搭起来（深入）
  │     └── join-flow.md      ——    新机器怎么接入
  ├── self-heal.md            —— 坏了怎么自愈
  ├── client-onboarding.md    —— 怎么加新 AI 客户端
  └── security.md             —— 怎么保证安全
```

## 术语速查

| 术语 | 含义 |
|---|---|
| Vault | Obsidian 的知识库目录（就是一堆 Markdown 文件的文件夹） |
| Raw 层 | 原始会话证据（AI 聊天记录/简报/剪藏），只读不改 |
| Wiki 层 | AI 从聊天里提炼出的结构化知识（概念/实体/主题/来源摘要） |
| Lessons | 经验卡：踩坑、排查、可复用的解决方案 |
| Schema 层 | 规则 + 索引 + 变更日志（约束 AI 不乱写） |
| 蒸馏 | 让一个 LLM 读聊天记录、提炼成知识页面的过程（每 4h 一次） |
| 拉取 | 服务器用 SSH 把 Mac 上的 AI 会话复制过来 |
| 导出 | 把各 AI 的原始会话格式转成统一的 Markdown |
| FTS5 | SQLite 全文索引（像给所有笔记建了个搜索引擎） |
| ChromaDB | 向量数据库（按语义相似度检索，能搜「意思相近」的内容） |
| systemd timer | Linux 上的定时任务（相当于 Mac 的「日历提醒」） |
| crontab | Linux 上的另一个定时任务机制 |
| .hermes-nodes | 新机器注册标记目录（服务器靠它发现新 Mac） |
| 双向同步 | 服务器和 Mac 互相更新对方的新文件（不带删除） |
| fallback 链 | 主 LLM 失败时自动换备用的降级机制 |
