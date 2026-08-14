# 知识库目录结构

Vault 的标准结构（渐进式披露设计）：

```txt
Vault/
├── CLAUDE.md              # AI 总入口（身份确认 + 文件夹地图）
├── Context/               # 人物背景
│   ├── about-me.md        # 我是谁
│   ├── goals.md           # 目标和当前关注
│   └── writing-style.md   # 表达风格
├── Wiki/                  # 结构化知识层（核心）
│   ├── AGENTS.md          # Wiki 维护规范
│   ├── Sources/           # 来源摘要：YYYY-MM-DD-标题.md
│   ├── Concepts/          # 概念
│   ├── Entities/          # 实体（工具/人/项目）
│   ├── Topics/            # 主题综述（跨来源长期主题）
│   ├── Index.md           # 索引
│   └── Log.md             # 变更日志（只追加）
├── {工具}/                # 每个 AI 工具一个目录
│   ├── Chat Logs/         # Raw 聊天记录（只读）
│   │   └── assets/        # 图片
│   └── Lessons/           # 工具特有经验
├── Shared/Lessons/        # 跨工具经验
├── Skills/                # 可复用任务配置
├── Daily Notes/           # 每日碎碎念
├── 简报/                  # 定期简报成品
└── Clippings/             # Web Clipper 收藏
```

## 渐进式披露原则

```txt
整体地图 → CLAUDE.md
文件夹局部规则 → 各文件夹的 instructions.md
AI 只读当下需要的那一层，不一次扫描整个 vault
```

## Wiki 维护规范（AGENTS.md 核心）

1. Raw 层原文不改写、不删除；更正只在 Wiki 页记录
2. 每份重要资料先在 Sources 建摘要页
3. 事实性内容标注来源；无法确认写"待核实"
4. 新旧冲突：并列保留，标注来源/时间/失效原因，不覆盖旧结论
5. 更新页面同步维护 Index + Log
6. 敏感信息脱敏
