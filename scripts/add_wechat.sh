#!/usr/bin/env bash
#
# Hermes 微信一键添加脚本
# 用法: ./add_wechat.sh <profile名字>
# 示例: ./add_wechat.sh wechat2
#
set -euo pipefail

PROFILE="${1:-}"
if [ -z "$PROFILE" ]; then
  echo "用法: $0 <profile名字>"
  echo "示例: $0 wechat2"
  exit 1
fi

export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"

echo ""
echo "═══════════════════════════════════════════════"
echo "  💬 添加新微信 — Profile: $PROFILE"
echo "═══════════════════════════════════════════════"
echo ""

# ── 1. 检查是否已存在 ──
if hermes profile list 2>/dev/null | grep -qw "$PROFILE"; then
  echo "⚠️  Profile '$PROFILE' 已存在"
  read -p "覆盖重新配置？(y/N) " -n 1 -r
  echo
  [[ ! $REPLY =~ ^[Yy]$ ]] && exit 0
else
  # ── 2. 创建 Profile（克隆 default）──
  echo "① 创建 Profile '$PROFILE'..."
  hermes profile create "$PROFILE" --clone
  echo ""
fi

# ── 3. 设置默认配置 ──
echo "② 配置模型和人格..."
hermes -p "$PROFILE" config set model.default glm-5.2
hermes -p "$PROFILE" config set model.provider zai
hermes -p "$PROFILE" config set model.base_url '""'
hermes -p "$PROFILE" config set display.personality helpful
hermes -p "$PROFILE" config set approvals.mode smart
echo "   ✅ 模型: glm-5.2 / 人格: helpful / 审批: smart"
echo ""

# ── 4. 微信扫码 ──
echo "③ 微信扫码登录..."
echo "   终端会显示二维码，用微信扫描确认。"
echo ""
read -p "开始扫码？(Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
  hermes -p "$PROFILE" gateway setup
fi

# ── 5. 安装为系统服务 ──
echo ""
echo "④ 安装为系统服务（开机自启）..."
read -p "安装 systemd 服务？(Y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
  hermes -p "$PROFILE" gateway install
  hermes -p "$PROFILE" gateway start
fi

# ── 6. 完成 ──
echo ""
echo "═══════════════════════════════════════════════"
echo "  ✅ 完成！Profile '$PROFILE' 已就绪"
echo "═══════════════════════════════════════════════"
echo ""
echo "  Profile 列表:"
hermes profile list 2>/dev/null
echo ""
echo "  管理:"
echo "    hermes -p $PROFILE gateway status    # 状态"
echo "    hermes -p $PROFILE gateway restart   # 重启"
echo "    hermes -p $PROFILE config set ...    # 改配置"
echo ""
echo "  对话导出: 每小时自动写入 Daily Notes/Hermes-$PROFILE-*.md"
echo ""
