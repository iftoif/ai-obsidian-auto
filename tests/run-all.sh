#!/usr/bin/env bash
# 一键全量回归：L0 静态 → L1 单元 → L2 集成 → L3 冒烟 → L4 安全 → L5 变异
# 用法：bash tests/run-all.sh
# 任一层失败即退出非零（CI 同款判定）
set -uo pipefail

# ~/.local/bin 可能有 shellcheck/bats（本机安装位置），补进 PATH
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

PASS=0; FAIL=0; SKIP=0

section() { echo; echo "═══ $1 ═══"; }
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }
skip() { echo "  ⏭️  $1"; SKIP=$((SKIP+1)); }

# ── L0 静态分析 ──
section "L0 静态分析（shellcheck + py_compile）"
if command -v shellcheck >/dev/null 2>&1; then
  ERRORS=$(shellcheck -x scripts/*.sh tests/*.sh tests/integration/*.sh tests/security/*.sh tests/unit/*.bats 2>&1 | grep -cE ':[0-9]+:[0-9]+: (error|warning)' || true)
  if [ "$ERRORS" -eq 0 ]; then ok "shellcheck 零 error/warning"; else bad "shellcheck 有 $ERRORS 个 error/warning"; fi
else
  skip "shellcheck 未安装（brew install shellcheck）"
fi
if python3 -m py_compile scripts/*.py 2>/dev/null; then ok "py_compile 通过"; else bad "py_compile 失败"; fi

# ── L1 单元测试 ──
section "L1 单元测试（pytest + bats）"
if python3 -m pytest tests/unit/ -q >/tmp/runall-pytest.log 2>&1; then
  N=$(python3 -m pytest tests/unit/ --collect-only 2>/dev/null | grep -oE '[0-9]+ tests collected' | grep -oE '[0-9]+')
  [ -z "$N" ] && N='?'
  ok "pytest: $N 用例通过"
else
  bad "pytest 失败"; tail -10 /tmp/runall-pytest.log
fi
if command -v bats >/dev/null 2>&1; then
  if bats tests/unit/*.bats >/tmp/runall-bats.log 2>&1; then
    ok "bats: $(grep -c '^ok ' /tmp/runall-bats.log) 通过"
  else
    bad "bats 失败"; tail -5 /tmp/runall-bats.log
  fi
else
  skip "bats 未安装（brew install bats-core）"
fi

# ── L2 集成测试 ──
section "L2 集成测试"
for t in tests/integration/*.sh; do
  if bash "$t" >/tmp/runall-integ.log 2>&1; then
    ok "$(basename "$t") 通过（$(grep -oE '[0-9]+ 通过' /tmp/runall-integ.log | tail -1 | grep -oE '[0-9]+') 断言）"
  else
    bad "$(basename "$t") 失败"; tail -8 /tmp/runall-integ.log
  fi
done

# ── L3 冒烟 ──
section "L3 E2E 冒烟"
if bash tests/smoke.sh >/tmp/runall-smoke.log 2>&1; then
  ok "冒烟: $(grep -oE '[0-9]+ 通过 / [0-9]+ 失败' /tmp/runall-smoke.log | tail -1)"
else
  bad "冒烟失败"; tail -8 /tmp/runall-smoke.log
fi

# ── L4 安全矩阵 ──
section "L4 安全矩阵"
if bash tests/security/test_security_matrix.sh >/tmp/runall-sec.log 2>&1; then
  ok "安全: $(grep -oE '[0-9]+ 通过 / [0-9]+ 失败' /tmp/runall-sec.log | tail -1)"
else
  bad "安全矩阵失败"; tail -8 /tmp/runall-sec.log
fi

# ── L5 变异验证 ──
section "L5 变异验证"
if python3 tests/mutation.py >/tmp/runall-mut.log 2>&1; then
  ok "变异: $(grep -oE '[0-9]+ killed' /tmp/runall-mut.log | tail -1)"
else
  bad "变异验证失败"; tail -8 /tmp/runall-mut.log
fi

# ── 汇总 ──
echo
echo "═══════════════════════════════════"
echo "  全量回归：$PASS 通过 / $FAIL 失败 / $SKIP 跳过"
echo "═══════════════════════════════════"
rm -f /tmp/runall-*.log
[ "$FAIL" -eq 0 ]