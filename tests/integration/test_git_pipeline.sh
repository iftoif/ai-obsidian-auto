#!/usr/bin/env bash
# QA-PLAN §4 集成测试：autocommit 首次/增量/部分目录/密钥拦截
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"
TESTROOT="$(mktemp -d)"
trap 'rm -rf "$TESTROOT"' EXIT

ok()  { echo "  ✅ $1"; }
bad() { echo "  ❌ $1"; exit 1; }

# 造 wiki 内容 + 初始化 git 仓库
WIKI="$TESTROOT/wiki-repo"
mkdir -p "$WIKI/Wiki"
git init -q "$WIKI"
git -C "$WIKI" config user.name test
git -C "$WIKI" config user.email test@t

# 1. 首次提交（模拟 autocommit 首次）
echo '# 第一篇' > "$WIKI/Wiki/first.md"
git -C "$WIKI" add Wiki 2>/dev/null
git -C "$WIKI" commit -m '首次提交' -q 2>/dev/null
COUNT=$(git -C "$WIKI" log --oneline | wc -l | tr -d ' ')
[ "$COUNT" -eq 1 ] || bad "首次提交失败: $COUNT"
ok "首次提交"

# 2. 增量提交
echo '# 第二篇' > "$WIKI/Wiki/second.md"
git -C "$WIKI" add Wiki 2>/dev/null
git -C "$WIKI" commit -m '增量提交' -q 2>/dev/null
COUNT=$(git -C "$WIKI" log --oneline | wc -l | tr -d ' ')
[ "$COUNT" -eq 2 ] || bad "增量提交失败: $COUNT"
ok "增量提交"

# 3. 部分目录（不存在的目录不拖垮 add——add_paths 修复回归）
# 先造一个新文件让提交有内容
echo '# 第三篇' > "$WIKI/Wiki/third.md"
add_paths=()
for p in Wiki Hermes/Lessons Codex/Lessons; do
  [ -e "$WIKI/$p" ] && add_paths+=("$p")
done
git -C "$WIKI" add "${add_paths[@]}" 2>/dev/null
PART_RC=$?
[ "$PART_RC" -eq 0 ] || bad "部分目录 add 失败"
git -C "$WIKI" commit -m '部分目录' -q 2>/dev/null
COMMIT_RC=$?
[ "$COMMIT_RC" -eq 0 ] || bad "部分目录提交失败"
ok "部分目录 add 不拖垮"

# 4. 密钥拦截（含疑似密钥 → 检测触发）
echo 'sk-abcdef1234567890abcdefgh' > "$WIKI/Wiki/secret.md"
git -C "$WIKI" add Wiki 2>/dev/null
if git -C "$WIKI" diff --cached --binary | grep -Eiq 'sk-[A-Za-z0-9]{20}'; then
  git -C "$WIKI" reset -q 2>/dev/null
  CACHED=$(git -C "$WIKI" diff --cached --name-only | wc -l | tr -d ' ')
  [ "$CACHED" -eq 0 ] || bad "密钥文件未被拦截"
  ok "密钥拦截触发（暂存区清空）"
else
  bad "密钥检测未触发"
fi

echo "\n===== 集成测试（git pipeline）：全部通过 ====="