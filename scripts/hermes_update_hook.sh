#!/bin/bash
# hermes 更新后自动修复 + 重启
set -euo pipefail

PYTHON="${HERMES_PYTHON:-$HOME/.hermes/hermes-agent/venv/bin/python3}"
PATCH_SCRIPT="$HOME/.hermes/scripts/hermes_patch.py"

echo "🔧 执行 Hermes 修复..."
$PYTHON "$PATCH_SCRIPT"

echo ""
echo "🔄 重启所有 gateway..."
for svc in hermes-gateway hermes-gateway-wechat2 hermes-gateway-wechat3; do
    systemctl --user restart "$svc" 2>/dev/null || true
done

sleep 5
echo "📊 状态:"
systemctl --user is-active hermes-gateway hermes-gateway-wechat2 hermes-gateway-wechat3 2>/dev/null

echo ""
echo "✅ 完成"
