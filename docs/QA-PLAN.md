# QA 计划：系统化 Bug 查找方法论

> 目标：把「人肉读代码找 bug」升级为「工具链 + 测试矩阵 + 变异验证」的科学流程。
> 参考：Google Code Review 方法论、OWASP 测试指南、bats-core 社区实践、变异测试（mutation testing）。

## 0. 核心思想

之前的循环（审阅→修复）低效的根因：**静态读代码对运行时行为迟钝**。
本计划的中心原则：**一切可测的行为必须有自动化测试；测试本身必须经过变异验证（能杀死变异体才算有效测试）**。

## 1. 分层策略（从外到内）

```text
L0 工具链静态分析（每秒跑，防低级错误）
L1 单元测试（bats + pytest，覆盖每个函数的边界）
L2 集成测试（脚本间交互、环境变量传递）
L3 端到端沙箱（完整部署 + 真实运行，模拟真实服务器）
L4 安全专项（OWASP 风格：注入、越权、投毒、信息泄露）
L5 变异验证（证明测试有效：注入 bug 必须被测试抓住）
```

## 2. L0：静态分析工具链（每次提交前跑）

```bash
# bash 脚本
shellcheck -x scripts/*.sh tests/*.sh        # 标准告警（error/warning 必须清零）

# Python
python3 -m py_compile scripts/*.py            # 语法
bandit -q -r scripts/                         # 安全静态分析（可选安装）
python3 -m pip install ruff -q && ruff check scripts/   # lint（可选）

# 自定义一致性检查（本项目特有）
bash tests/consistency.sh                     # 见 §7
```

## 3. L1：单元测试（bats-core + pytest）

### 3.1 bash 函数单元测试（bats-core）

安装：`brew install bats-core` 或 `apt install bats`

```bash
# tests/unit/*.bats 结构
tests/unit/
├── mac-session-pull.bats   # IP 校验、hostname 空值、主 Mac 跳过
├── node-discovery.bats     # 公钥校验、注册源校验、去重
├── vault-pull.bats         # 变量缺省、路径构建
├── setup-server.bats       # 必填校验、unit 生成、crontab
├── autocommit.bats         # git init、add_paths、密钥拦截
└── distill.bats            # fallback 链、hermes 解析
```

### 3.2 Python 单元测试（pytest）

```bash
# tests/unit/test_*.py
test_parse_time.py        # 秒/毫秒/微秒/极大/字符串/异常
test_parse_frontmatter.py # 内联/block/畸形/空值/缩进续行
test_redact_secrets.py    # 各模式、二次污染、UNSTORED、占位符跳过
test_event_hash.py        # 行号去重语义
test_save_image.py        # 文件名唯一性、短图片拒绝
test_search_sqlite.py     # FTS5 + LIKE fallback、中文
```

## 4. L2：集成测试（脚本间交互）

```bash
# tests/integration/
test_env_propagation.sh   # .env → setup-server → systemd Environment → 脚本读取 全链路
test_export_pipeline.sh   # 假 session jsonl → ai_chat_export → Raw md → 蒸馏 dry-run
test_backup_pipeline.sh   # 假 vault → obsidian_backup → FTS5 → Chroma(降级) → state
test_git_pipeline.sh      # autocommit 首次/增量/部分目录/密钥拦截
```

## 5. L3：端到端沙箱（真实运行，模拟服务器）

`tests/smoke.sh` 升级为完整 E2E：

```bash
# 新增场景（对照已发现 bug 清单，每个历史 bug 一条回归）
1. 全新服务器部署（空 crontab）         # R10 bug
2. .env 缺必填项 → 友好报错             # R15 bug
3. .env 含尖括号占位符 → source 通过     # R12 bug
4. 非法 IP 注册标记 → 拒绝              # R15 bug
5. 含空格路径 → --protect-args          # R15 bug
6. 同 session 两张图 → 文件名不冲突      # R14 bug
7. 微秒时间戳 → 不抛异常                # R13 bug
8. 重复消息 → 都导出（line_no）         # R12 bug
9. sec_xy-z 引用 → 不二次污染           # R13 bug
10. hermes 不在 PATH → 明确报错         # R15 bug
```

## 6. L4：安全专项（OWASP 风格）

### 6.1 注入类

```bash
# 对所有接受外部输入的脚本（node-discovery/mac-session-pull/vault-pull/export-all）
# 构造以下输入矩阵：
1. 命令注入:   lan_ip='10.0.0.1; rm -rf /'  / user='$(whoami)'
2. 路径注入:   hostname='../../etc/passwd'
3. 换行注入:   ssh_pubkey 含 \n
4. 空值/缺失:  所有字段缺失 / 空 JSON / 非 JSON
5. 超大值:    hostname 100KB / lan_ip 100KB
6. 类型混淆:  lan_ip=数字 / hostname=数组
```

### 6.2 信息泄露类

```bash
# 仓库自检（防真实信息入库）：
1. 当前树 + git 历史扫描（IP/用户名/密钥/邮箱/域名）
2. 脚本输出/日志/告警是否含敏感信息
3. .env 是否可能被提交（.gitignore 验证）
4. 公钥/密钥形态扫描（sk-/AKIA/ghp_/BEGIN PRIVATE）
```

### 6.3 权限类

```bash
# authorized_keys 写入：umask、flock、权限断言、幂等
# systemd unit：ExecStart 路径存在性、Environment 注入完整性
# 临时文件：/tmp 文件是否可预测（$$ vs mktemp）、是否清理
```

## 7. 一致性检查（本项目特有，脚本化）

```bash
# tests/consistency.sh 自动检查：
1. templates/*.timer ↔ setup-server 生成的调度一致
2. 8 个 timer 都有 template + 生成 + 启用
3. .env.example 变量 ↔ 脚本引用变量（无未定义/未使用）
4. 文档引用的文件/unit/命令都存在（无幽灵引用）
5. 脚本内部互调路径（SCRIPT_DIR）与部署方式一致
6. 硬编码 HERMES_HOME 残留扫描
7. 占位符残留（your-provider/your-model/<your-key>）
```

## 8. L5：变异验证（证明测试有效）

这是本计划的核心创新：**测试是否能抓住注入的 bug**。

```bash
# tests/mutation.sh：对每个关键文件做变异注入
# 例如对 setup-server.sh 注入这些变异：

1. 删除 [ -n "\${VAR:-}" ] 中的 :-   → 测试应报错（unbound 回归）
2. 删除 --protect-args                  → 空格路径测试应失败
3. 删除 IP 范围校验                     → 999.999 测试应失败
4. 把 line_no 从 event_hash 去掉        → 重复消息测试应失败
5. 把 save_image line_no 去掉           → 双图测试应失败
6. 把 SECRET_REF_RE 的 - 去掉           → sec_xy-z 测试应失败

# 验收标准：注入的每个变异体都被至少一个测试抓住（kill rate = 100%）
# 否则说明测试矩阵有盲区，先补测试再继续
```

## 9. 执行顺序（每轮）

```text
1. git pull 对齐最新 → git log -1 --oneline 记录基线
2. 跑 L0（shellcheck + py_compile + consistency）→ 修到清零
3. 跑 L1+L2（bats + pytest + 集成）→ 修到全绿
4. 跑 L3（smoke 全场景）→ 修到全绿
5. 跑 L4（安全矩阵）→ 修到全绿
6. 跑 L5（变异验证）→ kill rate 100% 才允许收尾
7. 全部通过 → 本轮零发现 → 收敛确认
```

## 10. 收敛标准（什么时候算「没 bug 了」）

```text
不是「我读了三遍没发现问题」，而是：
1. 所有 L0-L4 检查全绿（工具 + 测试矩阵都通过）
2. L5 变异 kill rate = 100%（测试没有盲区）
3. 新增 5 个随机变异体也 100% 被抓住（抽样验证）
4. 连续 2 轮执行完整流程零新增
```

## 11. 工具安装清单

```bash
brew install bats-core shellcheck        # macOS
# 或 apt install bats shellcheck         # Linux
pip install bandit ruff pytest           # Python 工具链
```
