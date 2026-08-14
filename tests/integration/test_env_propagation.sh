#!/usr/bin/env bash
# 集成测试：.env → setup-server → systemd Environment → 脚本读取 全链路
# 用法：bash tests/integration/test_env_propagation.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTROOT="$(mktemp -d /tmp/qa-integ.XXXXXX)"
PASS=0; FAIL=0
trap 'rm -rf "$TESTROOT"' EXIT
ok(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
bad(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }

mkdir -p "$TESTROOT/repo" "$TESTROOT/bin" "$TESTROOT/home/.config/systemd/user"
cp -r "$REPO/scripts" "$TESTROOT/repo/scripts"

# stub systemctl / crontab
printf '#!/bin/bash\necho "[systemctl] $*"\n' > "$TESTROOT/bin/systemctl"
cat > "$TESTROOT/bin/crontab" <<'EOF'
#!/bin/bash
if [ "$1" = "-l" ]; then exit 0; fi
cat > "$SMOKE_CRONTAB_OUT"
echo ok
EOF
chmod +x "$TESTROOT/bin/systemctl" "$TESTROOT/bin/crontab"
export SMOKE_CRONTAB_OUT="$TESTROOT/cron.txt"

cat > "$TESTROOT/repo/.env" <<EOF
SERVER_USER=tester
OBSIDIAN_VAULT_PATH=$TESTROOT/vault
HERMES_HOME=$TESTROOT/home/.hermes
PRIMARY_MAC_IP=10.0.0.99
SSH_USER=testermac
MAC_USER=testermac
AI_DISTILL_PROVIDER=openai-codex
AI_DISTILL_MODEL=gpt-5.6-luna
EOF

echo "▸ env 传播全链路"

# 1. setup-server 生成 unit
HOME="$TESTROOT/home" PATH="$TESTROOT/bin:$PATH" SKIP_PIP_INSTALL=1 bash "$TESTROOT/repo/scripts/setup-server.sh" >/dev/null 2>&1

# 2. 检查 unit 的 Environment 注入
if grep -q 'Environment="OBSIDIAN_VAULT_PATH=' "$TESTROOT/home/.config/systemd/user/vault-pull.service"; then
  ok "unit 注入 OBSIDIAN_VAULT_PATH"
else
  bad "unit 未注入 OBSIDIAN_VAULT_PATH"; cat "$TESTROOT/home/.config/systemd/user/vault-pull.service"
fi

# 3. 模拟 systemd 注入环境变量运行 vault-pull（SSH 不可达应优雅退出）
if perl -e 'alarm 30; exec @ARGV' env HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" PRIMARY_MAC_IP='10.0.0.99' SSH_USER='testermac' MAC_USER='testermac' bash "$REPO/scripts/vault-pull.sh" >/dev/null 2>&1; then
  ok "vault-pull 在注入环境下 exit 0"
else
  bad "vault-pull 在注入环境下失败"
fi

# 4. 无环境变量（手工路径）→ .env 兜底生效
if perl -e 'alarm 30; exec @ARGV' env HOME="$TESTROOT/home" bash "$REPO/scripts/vault-pull.sh" >/dev/null 2>&1; then
  ok "vault-pull 无环境变量时 .env 兜底 exit 0"
else
  bad "vault-pull 无环境变量时失败"
fi

# 5. 缺必填项 → 友好报错
rm -rf "$TESTROOT/repo2"; mkdir -p "$TESTROOT/repo2/scripts"
cp -r "$REPO/scripts/"* "$TESTROOT/repo2/scripts/"
cat > "$TESTROOT/repo2/.env" <<EOF
OBSIDIAN_VAULT_PATH=$TESTROOT/vault
SSH_USER=test
EOF
if { HOME="$TESTROOT/home" PATH="$TESTROOT/bin:$PATH" SKIP_PIP_INSTALL=1 bash "$TESTROOT/repo2/scripts/setup-server.sh" 2>&1 || true; } | grep -q '请填写 PRIMARY_MAC_IP'; then
  ok "缺 PRIMARY_MAC_IP → 友好报错"
else
  bad "缺 PRIMARY_MAC_IP 未友好报错"
fi

echo
echo "===== 集成测试：$PASS 通过 / $FAIL 失败 ====="
[ "$FAIL" -eq 0 ]