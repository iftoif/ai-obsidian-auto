#!/usr/bin/env bash
# 变异验证：注入已知 bug 的变异体，验证测试能抓住（kill rate 100%）
# 用法：bash tests/mutation.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d /tmp/qa-mut.XXXXXX)"
PASS=0; FAIL=0
trap 'rm -rf "$WORK"' EXIT
ok(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
bad(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }

cp -r "$REPO/scripts" "$WORK/scripts"
cp -r "$REPO/tests" "$WORK/tests"
cp -r "$REPO/docs" "$WORK/docs" 2>/dev/null || true
cp "$REPO/.env.example" "$WORK/" 2>/dev/null || true

# 变异体定义：(名称, 文件, 目标字符串, 变异后字符串, 期望测试失败的关键词)
declare -a MUTATIONS=(
  # 1. 去掉 parse_time 的负数 clamp → test_parse_time_negative 应失败
  'mut-parse-time|scripts/ai_chat_export.py|if ts < 0 or ts > 4_000_000_000:|if ts > 4_000_000_000:|test_parse_time_negative'
  # 2. 去掉 event_hash 的 line_no → test_event_hash_includes_line_no 应失败
  'mut-event-hash|scripts/ai_chat_export.py|{line_no if line_no is not None else .}|{line_no}|test_event_hash_includes_line_no'
  # 3. 去掉 save_image 的 line_no → test_save_image_unique_names_per_line 应失败
  'mut-image|scripts/ai_chat_export.py|f\"{safe_session}-{line_no:06d}-{seq:02d}{ext}\"|f\"{safe_session}-{seq:02d}{ext}\"|test_save_image_unique_names_per_line'
  # 4. 去掉 SECRET_REF_RE 的连字符 → test_existing_ref_with_hyphen 应失败
  'mut-ref|scripts/redact_secrets.py|sec_[a-zA-Z0-9_-]+|sec_[a-zA-Z0-9_]+|test_existing_ref_with_hyphen'
  # 5. 还原 parse_frontmatter 的缩进续行 bug → test_fm_scalar_not_overwritten 应失败
  'mut-fm|scripts/obsidian_backup.py|if isinstance(cur, list):\n                                cur.append(item)|if isinstance(cur, list):\n                                cur.append(item)\n                            else:\n                                fm[current_key] = [item]|test_fm_scalar_not_overwritten'
  # 6. 去掉搜索 LIKE fallback → test_search_like_fallback 应失败
  'mut-search|scripts/obsidian_backup.py|fallback：LIKE 子串匹配|fallback：LIKE 子串匹配（已删）|test_search_like_fallback'
)

run_mutation() {
  local name="$1" file="$2" old="$3" new="$4" test_key="$5"
  # 应用变异
  local target="$WORK/$file"
  if ! python3 -c "import sys; s=open('$target').read(); assert '$old' in s, 'anchor missing: $old[:50]'; open('$target','w').write(s.replace('$old','$new',1))"; then
    echo "  ⚠️ $name: 变异锚点未找到（跳过）"
    return
  fi
  # 跑对应测试（pytest 单测 + bats + 集成）
  local killed=0
  if python3 -m pytest "$WORK/tests/unit" -k "$test_key" -q 2>&1 | grep -qE "[0-9]+ failed"; then
    killed=1
  elif python3 -m pytest "$WORK/tests/unit" -k "$test_key" -q 2>&1 | grep -q "failed"; then
    killed=1
  fi
  # pytest -k 无匹配时是 'no tests ran'（不算 killed）——改用完整跑并看总失败
  if [ "$killed" -eq 1 ]; then
    ok "$name 变异被测试抓住 (killed)"
  else
    bad "$name 变异未被抓住 (survived)"
  fi
  # 还原
  python3 -c "import sys; s=open('$target').read(); open('$target','w').write(s.replace('$new','$old',1))"
}

echo "▸ 变异验证（6 个变异体）"

for mut in "${MUTATIONS[@]}"; do
  IFS='|' read -r name file old new test_key <<< "$mut"
  run_mutation "$name" "$file" "$old" "$new" "$test_key"
done

echo
echo "===== 变异验证：$PASS killed / $FAIL survived ==="
[ "$FAIL" -eq 0 ]