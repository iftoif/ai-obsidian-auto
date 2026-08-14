# Raw-Wiki-Schema 三层知识库设计

> 这是整套系统的知识组织核心：让 AI 在「不破坏原始证据」的前提下，增量维护一个可追溯、可链接、可自生长的知识库。

## 1. 三层模型

| 层 | 内容 | 位置 | 谁维护 | 规则 |
|---|---|---|---|---|
| **Raw** | 原始证据：聊天记录、简报、剪藏、日记 | `*/Chat Logs/`、`简报/`、`Clippings/`、`Daily Notes/` | 自动化导出脚本 | 只读、不改写、不删除、不移动 |
| **Wiki** | AI 维护的结构化理解 | `Wiki/Sources/` `Wiki/Concepts/` `Wiki/Entities/` `Wiki/Topics/` + 各工具 `Lessons/` | AI（蒸馏） | 可更新，但必须保留来源；冲突并列保留 |
| **Schema** | 规则、索引、日志 | `CLAUDE.md`、`Wiki/AGENTS.md`、`Wiki/Index.md`、`Wiki/Log.md`、各目录 `instructions.md` | 人 + AI | 约束 AI 的边界，防止乱建乱改 |

## 2. 为什么分层

传统 RAG 的痛点：资料进向量库，提问时临时召回片段，回答结束后知识结构**没有变化**，同类问题下次仍需重新拼接。

LLM Wiki 的目标是让知识库「留下变化」：

- 新概念被创建、旧页面被补充、相关页面建立双链
- 冲突观点保留来源、时间、适用范围，不强行合并
- 每次维护都写入变更日志，可审计

## 3. Wiki 层四类页面

### Sources（来源摘要）

- 命名：`YYYY-MM-DD-简短标题.md`
- 每份重要 Raw 资料建一个来源页，保留原始路径或 URL
- 是事实的「证据锚点」：概念/实体/主题页里的结论都通过 `sources` 字段指向这里

### Concepts（概念）

- 方法、理论、模式、技术概念
- 结构（见 `templates/concept-template.md`）：定义 / 解决的问题 / 关键机制 / 在系统中的应用 / 与其他概念的关系 / 风险与边界 / 来源 / 待核实

### Entities（实体）

- 人、公司、产品、工具、服务器、模型、项目
- 例：`Obsidian`、`Codex`、`Hermes`、`Futu OpenD`、`OpenCodex`

### Topics（主题）

- 跨来源的长期主题综述，高密度
- 例：`个人 AI 第二大脑架构`、`系统完整部署手册`、`美股期权策略系统`
- 查询时优先读 Topics → Concepts/Entities → Lessons → Raw

## 4. 页面元数据（frontmatter）

```yaml
---
title: 概念名
type: concept            # concept | entity | topic | source | lesson | index | log
aliases: []
tags: [concept, ...]
sources:                # 事实来源，指向 Sources 页或外部链接
  - "[[2026-08-10-xxx]]"
created: 2026-08-10
updated: 2026-08-14
---
```

## 5. 维护规则（Wiki/AGENTS.md 摘要）

1. 处理新资料前，先搜索 Wiki 中已有页面，判断补充旧页还是创建新页
2. Raw 层原文不改写、不删除、不移动；如需更正，只在 Wiki 页中记录说明
3. 每份重要 Raw 资料先建 Source 摘要页
4. 概念、实体、主题独立成页，用 Obsidian 双链连接，不把所有信息堆在一个总结里
5. 事实性内容必须标注来源；无法确认的写「待核实」
6. **冲突处理**：同时保留不同说法及其来源、时间、适用范围、失效条件，不直接覆盖旧结论
7. 每次只更新受影响页面，并同步维护 `Wiki/Index.md` 与 `Wiki/Log.md`
8. `Wiki/Log.md` 只追加，不重写历史
9. 不擅自删除页面；同名文件已存在时，先读取并增量合并
10. 涉及 token / 密码 / 账号 / 私密路径时必须脱敏，只保留必要结论

## 6. 入库流程

```text
1. 确认 Raw 来源（URL / 文件 / 聊天记录 / 简报 / 人工输入）
2. 创建或更新 Wiki/Sources/<日期>-<标题>.md
3. 提取并维护 Concepts / Entities / Topics
4. 为新增/更新页面添加双链与 sources
5. 更新 Wiki/Index.md
6. 追加 Wiki/Log.md
```

## 7. 渐进式披露

根 `CLAUDE.md` 是总入口（含文件夹地图）→ 每个子文件夹自带 `instructions.md` → 任务中只读当下需要的层。

原则：**整体地图放根，细节放各层，每次只给当下需要的上下文**。随着知识库变大，这条越来越重要。

## 8. 与 RAG 的对比

| 维度 | RAG | LLM Wiki |
|---|---|---|
| 主要动作 | 临时召回片段 | 持续维护页面 |
| 知识是否成长 | 通常不成长 | 每次处理后留下变化 |
| 证据追溯 | 依赖检索结果 | Source 页 + Raw 链接 |
| 冲突处理 | 容易被总结抹平 | 并列保留来源与条件 |
| 适合场景 | 即问即答 | 长期个人知识库 |
