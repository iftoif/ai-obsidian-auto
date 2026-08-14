#!/usr/bin/env bash
# Hermes 自愈脚本：检测代码目录是否丢失，自动重新绑定
# 设计原则：
#   - 只用系统 bash + /usr/bin/python3（不依赖 hermes-agent，避免自己也断）
#   - 幂等（重复跑无害）
#   - 找不到新目录就告警，不破坏现状
set -uo pipefail


# 配置兜底：优先环境变量（systemd 注入），回退 source 仓库 .env（手工部署路径）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$REPO_DIR/.env" ]; then
  set -a; . "$REPO_DIR/.env"; set +a
fi

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
CODE_DIR="$HERMES_HOME/hermes-agent"
VENV_PY="$CODE_DIR/venv/bin/python"
LOG="$HERMES_HOME/logs/self-heal.log"
SYSTEMD_DIR="$HOME/.config/systemd/user"
GATEWAY_SERVICES="hermes-gateway hermes-gateway-wechat2 hermes-gateway-wechat3"

mkdir -p "$(dirname "$LOG")"
exec >>"$LOG" 2>&1
echo "=== self-heal check $(date '+%Y-%m-%d %H:%M:%S') ==="

# 1. 健康检查：代码目录还在吗？
if [ -x "$VENV_PY" ]; then
  echo "✅ 健康：$VENV_PY 存在，无需自愈"
  exit 0
fi

echo "⚠️ 检测到 hermes 代码目录缺失：$VENV_PY"

# 2. 自动发现新代码目录
NEW_PY=""

# 方式1：软链接 ~/.local/bin/hermes 指向新位置
if [ -L "$HOME/.local/bin/hermes" ]; then
  LINK_TARGET=$(readlink -f "$HOME/.local/bin/hermes" 2>/dev/null || echo "")
  if [ -x "$LINK_TARGET" ]; then
    NEW_PY=$(dirname "$LINK_TARGET")/python
  fi
fi

# 方式2：command -v hermes
if [ -z "$NEW_PY" ] || [ ! -x "$NEW_PY" ]; then
  CMD_HERMES=$(command -v hermes 2>/dev/null || echo "")
  if [ -n "$CMD_HERMES" ] && [ -x "$CMD_HERMES" ]; then
    RESOLVED=$(readlink -f "$CMD_HERMES" 2>/dev/null || echo "$CMD_HERMES")
    NEW_PY=$(dirname "$RESOLVED")/python
  fi
fi

# 方式3：扫描常见候选目录
if [ -z "$NEW_PY" ] || [ ! -x "$NEW_PY" ]; then
  for cand in \
    "$HERMES_HOME/hermes-agent/venv/bin/python" \
    "/usr/local/lib/hermes-agent/venv/bin/python" \
    "$HOME/hermes-agent/venv/bin/python" \
    "/opt/hermes-agent/venv/bin/python"; do
    if [ -x "$cand" ]; then
      NEW_PY="$cand"
      break
    fi
  done
fi

if [ -z "$NEW_PY" ] || [ ! -x "$NEW_PY" ]; then
  echo "❌ 无法自动发现新的 hermes 代码目录，需要人工处理"
  echo "   候选位置检查失败，请手动重装 Hermes 到默认目录 $CODE_DIR"
  exit 1
fi

echo "✅ 找到新代码目录 python: $NEW_PY"
NEW_HERMES=$(dirname "$NEW_PY")/hermes

# 3. 更新软链接
if [ -x "$NEW_HERMES" ]; then
  mkdir -p "$HOME/.local/bin"
  ln -sf "$NEW_HERMES" "$HOME/.local/bin/hermes"
  echo "✅ 软链接已更新: ~/.local/bin/hermes → $NEW_HERMES"
fi

# 4. 更新 systemd 服务的 ExecStart（把旧 python 路径换成新路径）
OLD_PATTERN="$HERMES_HOME/hermes-agent/venv/bin/python"
changed=0
for svc in $GATEWAY_SERVICES; do
  f="$SYSTEMD_DIR/$svc.service"
  [ -f "$f" ] || continue
  if grep -q "$OLD_PATTERN" "$f"; then
    cp "$f" "$f.bak-$(date +%Y%m%d-%H%M%S)"   # 修改前自动备份（安全红线）
    sed -i "s|$OLD_PATTERN|$NEW_PY|g" "$f"
    echo "✅ $svc: ExecStart 已更新到 $NEW_PY"
    changed=1
  fi
done

# 5. 重载 + 重启 gateway
if [ "$changed" -eq 1 ]; then
  systemctl --user daemon-reload
  for svc in $GATEWAY_SERVICES; do
    systemctl --user restart "$svc" 2>/dev/null || true
  done
  echo "✅ systemd 已重载，gateway 已重启"
fi

# 6. 重跑 hermes_patch.py（恢复所有 patch）
PATCH="$HERMES_HOME/scripts/hermes_patch.py"
if [ -f "$PATCH" ] && [ -x "$NEW_PY" ]; then
  "$NEW_PY" "$PATCH" 2>&1 | tail -3
  echo "✅ hermes_patch.py 已重跑"
fi

echo "=== self-heal 完成 $(date '+%Y-%m-%d %H:%M:%S') ==="
