#!/usr/bin/env bash
# 重新应用图片落盘相关的 Hermes 源码 patch（升级后自动重放）
# 2026-08-14 创建：因为 hermes update 会 git pull 覆盖 base.py 的改动
set -uo pipefail

HERMES_AGENT="${HERMES_HOME:-$HOME/.hermes}/hermes-agent"
BASE_PY="$HERMES_AGENT/gateway/platforms/base.py"

# patch 1: cleanup_image_cache 改为 no-op（图片永久保留）
apply_cleanup_patch() {
  if [ ! -f "$BASE_PY" ]; then
    echo "⚠️ base.py 不存在，跳过"
    return
  fi
  # 检查是否已经 patch 过
  if grep -q "Images are now persisted into the Obsidian vault" "$BASE_PY" 2>/dev/null; then
    return  # 已 patch，无需重复
  fi
  # 检查目标代码块是否还在（未 patch 的原始状态）
  if grep -q 'return _cleanup_cache_dir(get_image_cache_dir(), max_age_hours)' "$BASE_PY" 2>/dev/null; then
    python3 - "$BASE_PY" <<'PY'
import sys
p = sys.argv[1]
with open(p) as f:
    c = f.read()
old = '''def cleanup_image_cache(max_age_hours: int = 24) -> int:
    """
    Delete cached images older than *max_age_hours*.

    Returns the number of files removed.
    """
    return _cleanup_cache_dir(get_image_cache_dir(), max_age_hours)'''
new = '''def cleanup_image_cache(max_age_hours: int = 24) -> int:
    """
    Delete cached images older than *max_age_hours*.

    Images are now persisted into the Obsidian vault (assets/weixin) via a
    symlink, so they must NOT be pruned. Returns 0 (no-op) to keep them
    permanent. (Patched 2026-08-14 — re-applied by reapply_image_patches.sh)
    """
    return 0'''
if old in c:
    c = c.replace(old, new, 1)
    with open(p, "w") as f:
        f.write(c)
    print("✅ cleanup_image_cache patch 已重新应用")
else:
    print("⚠️ cleanup_image_cache 代码块未匹配（Hermes 版本可能变了，需人工检查）")
PY
  else
    echo "⚠️ cleanup_image_cache 已被修改或代码结构变化，需人工检查"
  fi
}

apply_cleanup_patch
