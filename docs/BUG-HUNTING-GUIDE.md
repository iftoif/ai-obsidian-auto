# Bug Hunting Guide — 可复制的查 bug 方法论

> 这套流程不是玄学，是 20+ 轮审阅验证过的可复制方法。任何 AI 按步骤执行，
> 都能达到「每轮有新发现、发现必实测、测试不表演」的效果。
>
> 核心信念：**测试通过 ≠ 有覆盖；抓不住 bug 的测试是表演。**

## 0. 每轮执行顺序（15 分钟热身）

```text
1. git pull 对齐最新 → git log -1 --oneline 记录基线
2. git diff 上一轮之后的所有提交，逐提交读，把每个 commit message 当
   「待验证的断言」（不是结论）
3. 跑一遍仓库自带的全部测试（见 §9 命令）——先证明基线绿
4. 然后才开始找新 bug
```

## 1. 先对齐版本，再差异驱动审查

- 只 diff 上轮之后改了什么，不重扫全库
- 每个 commit message 都是「待验证的断言」：说修好了 X，就验证 X
- 多轮翻车根源：审阅者基于旧 commit 审查 → 报已修的问题。
  开工第一条命令必须是 `git log -1 --oneline` 确认基线

## 2. 报告的数字一律复跑，修复一律独立复现

- 别人说「114 全绿」→ 自己跑一遍
- 说「修好了」→ 用**和他们的测试不同的方法**再打一遍：
  - `--full` 残留 → 沙箱删文件重建再查
  - `--limit` → 造 3 条匹配验证截断
  - 占位符 → 直接跑 setup-server 真实执行
  - 中文搜索 → 用真实中文内容造库再搜
- 教训：`test_search_english_word` 测的是中文（复制粘贴测试）；
  mutation harness 一个都杀不死（断言现状而非期望）

## 3. 问「这代码在哪儿跑？那个环境有没有它要的东西？」

**这是最值钱的一条。** 多轮翻车的根源都是：

```text
测试环境（有 chromadb / sentence-transformers）比部署环境（setup-server
的 venv）富 → 测试全绿但服务器上静默回退。
```

- 每次修复都同时检查**一键部署路径**和**手工部署路径**是否都被覆盖
- 检查脚本引用的二进制/库在目标环境是否存在（flock、zstandard、chromadb、hermes）
- 检查版本兼容：rsync 老版本、bash 3.2、SQLite 版本

## 4. 静态找「死东西」

```text
- 无效参数：解析了但没用的 CLI 参数（--limit 等）
- 不可达分支：set -e 下的 EXIT=$? 永远 0
- 被吞掉的失败：|| true 吞 git add 失败 → 静默不提交
- 被 pipefail 掩盖的检查：cmd | grep 在 set -euo pipefail 下 if 恒 False
- 字符串嗅探代替显式信号：grep 输出内容判成败（应该看退出码）
- 死代码：any_new 变量、未用的 import
```

## 5. 元审查：审查测试本身

测试通过 ≠ 有覆盖。逐条检查：

```text
- skipif 掩盖缺依赖（test_semantic 在服务器上必然 skip，等于没测）
- 复制粘贴测试（名字说英文、内容测中文）
- 断言现状而非期望（assert True 或断言实现细节）
- 变异 harness 一个都杀不死 → 测试矩阵有盲区
- 测试隔离：空 CLAUDE_CONFIG_DIR 必须存在，否则 fallback 到真实 ~/.claude
  泄漏本机数据（测试污染真实环境）
```

## 6. 语言/领域特异性

- unicode61 分词对中文：整段中文当一个 token，子串搜索必无结果 →
  需要 LIKE fallback 或 trigram
- FTS5 子串搜不到、默认 embedding 是英文模型
- Obsidian 生态：aliases: [别名A]（无引号非 JSON）、frontmatter 缩进续行
- 中文用户高频开场「你好」被误判为冒烟测试

## 7. 每个发现必须实测复现才报

- 没复现的不算 bug（例：怀疑 .env 首行 [TEMPLATE] 会炸，查证是渲染
  假象 → 不报）
- 报 bug 附：复现命令 + 预期/实际对比
- 复现要最小化：单行脚本 > 完整场景

## 8. 诚实声明沙箱边界

```text
SSH 拉取、hermes 调用、微信/Telegram 网关、真实 ChromaDB——
这些只有真实环境才能验证。明确标出「测不了」，不装成「全验证过」。
```

## 9. 工具链（仓库已沉淀，跑进 CI 后机器强制）

```bash
# L0 静态：
shellcheck -x scripts/*.sh tests/*.sh   # 0 error / 0 warning
python3 -m py_compile scripts/*.py

# L1 单元：
python3 -m pytest tests/unit/ --cov=scripts   # 115+ 用例
~/.local/bin/bats tests/unit/*.bats

# L2 集成：
bash tests/integration/test_env_propagation.sh
bash tests/integration/test_export_pipeline.sh

# L3 E2E：
bash tests/smoke.sh   # 13 断言

# L4 安全：
bash tests/security/test_security_matrix.sh

# L5 变异（证明测试有效）：
python3 tests/mutation.py   # 10 变异体 kill rate 100%
```

## 10. 收敛判断

```text
不是「我读了三遍没发现问题」，而是：
1. 所有 L0-L4 检查全绿
2. L5 变异 kill rate = 100%
3. 每轮新增测试暴露的新 bug 数量递减（3→2→1→0）
4. 连续 2 轮完整流程零新增，才算收敛
```

## 11. 移植到生产系统时的额外纪律

```text
公开仓库是脱敏版，生产系统是硬编码版——文件级覆盖会破坏生产。
- 先全量备份（服务器端 .bak-qa-日期 + 本机备份目录）
- 按「修复点」精确移植，不按文件覆盖
- 高相似度文件（>90%）可移植，低相似度（<60%）只挑关键修复点
- 每个修复点先本地生成移植版 → pytest 验证 → 服务器备份 → 上传 →
  语法验证 → 真实运行验证 → 失败立即回滚
- 验证失败的修复点（如 --protect-args 与旧 rsync 不兼容）如实记录并回滚
```
