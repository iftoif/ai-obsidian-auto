#!/usr/bin/env bash
# QA-PLAN §7 一致性检查（自动执行 7 项）
# 用法：bash tests/consistency.sh
# 任一检查失败 exit 非零
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$REPO"

PASS=0; FAIL=0
ok()  { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad() { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
section() { echo; echo "═══ $1 ═══"; }

# ── 1. templates/*.timer ↔ setup-server 调度一致 ──
section "1. timer 模板 ↔ setup-server 调度"
# setup-server.sh 里 OnCalendar 与 templates 里的对比
for tmpl in templates/systemd/*.timer; do
  [ -f "$tmpl" ] || continue
  name=$(basename "$tmpl" .timer)
  # 模板里有 OnCalendar，setup-server 生成的也要有（关键调度值对齐）
  CAL=$(grep -oP '(?<=^OnCalendar=).*' "$tmpl" 2>/dev/null || grep -oE 'OnCalendar=.*' "$tmpl" | head -1 | cut -d= -f2-)
  if [ -n "$CAL" ]; then
    if grep -q "$name" scripts/setup-server.sh 2>/dev/null; then
      ok "$name: setup-server 引用"
    else
      bad "$name: setup-server 未引用"
    fi
  fi
done

# ── 2. 8 个核心 timer 都有 template + 生成 + 启用 ──
section "2. 核心 timer 三件套"
CORE_TIMERS="vault-pull node-discovery mac-session-pull hermes-self-heal obsidian-server-distill obsidian-server-index wiki-git-autocommit obsidian-server-chroma"
for t in $CORE_TIMERS; do
  has_tmpl=$([ -f "templates/systemd/$t.timer" ] && echo Y || echo N)
  if grep -q "$t" scripts/setup-server.sh 2>/dev/null; then has_gen=Y; else has_gen=N; fi
  if [ "$has_tmpl" = "Y" ] && [ "$has_gen" = "Y" ]; then
    ok "$t: template+生成"
  else
    bad "$t: template=$has_tmpl 生成=$has_gen（setup-server 未引用）"
  fi
done

# ── 3. .env.example 变量 ↔ 脚本引用（无未定义/未使用）──
section "3. .env 变量一致性"
# 提取 .env.example 定义的变量
ENV_VARS=$(grep -oE '^[A-Z_]+=' .env.example 2>/dev/null | tr -d '=' | sort -u)
# 提取脚本引用的变量（${VAR} 或 ${VAR:-} 形式）
USED_VARS=$(grep -rhoE '\$\{[A-Z_]+(:[-?]|}' scripts/*.sh 2>/dev/null | sed 's/^{//;s/}$//;s/:[-?].*$//' | sort -u)
UNDEFINED=0
for v in $USED_VARS; do
  case "$v" in
    HOME|PATH|USER|BASH_SOURCE|0|PWD|SHELL|TERM|LANG|LC_ALL|TZ|IFS|RANDOM|LINENO|PIPESTATUS|PPID|UID|GID|HOSTNAME) continue ;;
  esac
  if ! echo "$ENV_VARS" | grep -q "^$v$"; then
    # 脚本内部自赋值的不算（排除常见内部变量）
    echo "    ⚠️ 脚本引用但 .env 未定义: $v"
    UNDEFINED=$((UNDEFINED+1))
  fi
done
if [ "$UNDEFINED" -eq 0 ]; then ok ".env 变量引用无未定义"; else bad "$UNDEFINED 个未定义变量引用（见上）"; fi

# ── 4. 文档引用文件/unit/命令存在（无幽灵引用）──
section "4. 幽灵引用检查"
GHOST=0
for ref in $(grep -rhoE 'templates/systemd/[a-z-]+\.(service|timer)' docs/*.md 2>/dev/null | sort -u); do
  [ -f "$ref" ] || { echo "    ⚠️ 幽灵引用: $ref"; GHOST=$((GHOST+1)); }
done
for ref in $(grep -rhoE 'scripts/[a-z_-]+\.(sh|py)' docs/*.md 2>/dev/null | sort -u); do
  # 私有脚本白名单：服务器私有、公开仓库不含（docs 引用它们属正常）
  case "$ref" in
    scripts/secret_vault_export.py|scripts/chat_export.py|scripts/hermes_patch.py|scripts/keychain_secret.swift) continue ;;
  esac
  [ -f "$ref" ] || { echo "    ⚠️ 幽灵引用: $ref"; GHOST=$((GHOST+1)); }
done
if [ "$GHOST" -eq 0 ]; then ok "文档引用全部存在"; else bad "$GHOST 个幽灵引用"; fi

# ── 5. SCRIPT_DIR 与部署方式一致（脚本内互调路径）──
section "5. 脚本互调路径"
# 脚本间调用应该用 $SCRIPT_DIR（同目录互调）或 $REPO_DIR，不能硬编码
BAD_CALLS=0
for f in scripts/*.sh; do
  # 排除注释行，找对 scripts/ 下其他脚本的调用
  while read -r line; do
    if echo "$line" | grep -qE '(bash|exec|source|python3)[[:space:]]+[^$]'; then
      # 引用同目录脚本但没有 $SCRIPT_DIR/$REPO_DIR 前缀的
      if echo "$line" | grep -qE '(scripts/|hermes/scripts/)' && ! echo "$line" | grep -qE '\$(SCRIPT_DIR|REPO_DIR)'; then
        echo "    ⚠️ $f: 硬编码互调: $line"
        BAD_CALLS=$((BAD_CALLS+1))
      fi
    fi
  done < "$f"
done
if [ "$BAD_CALLS" -eq 0 ]; then ok "脚本互调全部走变量路径"; else bad "$BAD_CALLS 处硬编码互调"; fi

# ── 6. 硬编码 HERMES_HOME 残留扫描 ──
section "6. HERMES_HOME 残留"
HERMES_HARDCODE=$(grep -rlE '"/home/[a-z]+/\.hermes"|\$HOME/\.hermes' scripts/*.sh scripts/*.py 2>/dev/null | grep -vE 'HERMES_HOME[:=]' | wc -l | tr -d ' ')
# 实际检查：不应有硬编码 /home/xxx/.hermes 路径（应使用 $HERMES_HOME）
HC=$(grep -rnE '"/home/[a-z]+/\.hermes"' scripts/*.sh scripts/*.py 2>/dev/null | wc -l | tr -d ' ')
if [ "$HC" -eq 0 ]; then ok "无硬编码 HERMES_HOME 路径"; else bad "$HC 处硬编码路径（应改 \$HERMES_HOME）"; fi

# ── 7. 占位符残留（your-provider/your-model/<your-key>）──
section "7. 占位符残留"
PH=$(grep -rnE 'your-provider|your-model|<your-key>' scripts/ .env.example 2>/dev/null | wc -l | tr -d ' ')
if [ "$PH" -eq 0 ]; then ok "无占位符残留"; else bad "$PH 处占位符残留"; fi

echo
echo "═══════════════════════════════════"
echo "  一致性检查：$PASS 通过 / $FAIL 失败"
echo "═══════════════════════════════════"
[ "$FAIL" -eq 0 ]