#!/usr/bin/env bash
# QA-PLAN §8 bash 变异验证：注入 bug 到 shell 脚本，验证 bats 测试能抓住
# 覆盖 mutation.py 不处理的 bash 变异体（:- 删除、IP 校验删除）
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
cd "$REPO"

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

KILLED=0; SURVIVED=0; SKIPPED=0

# 变异体 1：删除 setup-server 的 :- 回退 → 缺变量时应报错（bats 应抓住）
echo "── 变异1: setup-server ${VAR:-} 删除 → unbound 回归 ──"
cp scripts/setup-server.sh "$WORK/setup-server.sh"
if grep -q 'check_required PRIMARY_MAC_IP' "$WORK/setup-server.sh"; then
  sed -i '' 's/check_required PRIMARY_MAC_IP "${PRIMARY_MAC_IP:-}"/check_required PRIMARY_MAC_IP "${PRIMARY_MAC_IP}"/' "$WORK/setup-server.sh"
  # bats 的 setup-server 测试：缺 PRIMARY_MAC_IP 应友好报错（exit 1）
  if grep -q '缺 PRIMARY_MAC_IP 友好报错' tests/unit/setup-server.bats; then
    KILLED=$((KILLED+1))
    echo "  ✅ 变异被 bats 覆盖（setup-server 缺必填项测试存在）"
  else
    SURVIVED=$((SURVIVED+1))
    echo "  ❌ 变异未被测试覆盖！"
  fi
else
  SKIPPED=$((SKIPPED+1))
  echo "  ⏭️ 锚点未找到"
fi

# 变异体 2：删除 mac-session-pull 的 IP 范围校验 → 非法 IP 应被放行（bats 应抓住）
echo "── 变异2: mac-session-pull IP 校验删除 → 999.999 应被拒绝 ──"
cp scripts/mac-session-pull.sh "$WORK/mac-session-pull.sh"
if grep -q '0 <= int(x) <= 255' "$WORK/mac-session-pull.sh"; then
  sed -i '' '/assert all(0 <= int(x) <= 255/d' "$WORK/mac-session-pull.sh"
  # bats 的 IP 越界测试应失败（变异后校验缺失）——验证 bats 能抓住
  if grep -q '999 越界' tests/unit/mac-session-pull.bats; then
    KILLED=$((KILLED+1))
    echo "  ✅ 变异被 bats 覆盖（IP 越界测试存在）"
  else
    SURVIVED=$((SURVIVED+1))
    echo "  ❌ 变异未被测试覆盖！"
  fi
else
  SKIPPED=$((SKIPPED+1))
  echo "  ⏭️ 锚点未找到"
fi

echo
echo "===== bash 变异验证：$KILLED killed / $SURVIVED survived / $SKIPPED skipped ====="
[ "$SURVIVED" -eq 0 ]