#!/usr/bin/env bats

# setup-server 核心逻辑单元测试（必填校验 / unit 生成 / crontab）

setup() {
  TESTROOT="$(mktemp -d)"
  export TESTROOT HOME="$TESTROOT/home"
  mkdir -p "$TESTROOT/repo/scripts" "$TESTROOT/bin" "$HOME/.config/systemd/user"
  # stub systemctl / crontab
  printf '#!/bin/bash
echo "[systemctl] $*"
' > "$TESTROOT/bin/systemctl"
  cat > "$TESTROOT/bin/crontab" <<'EOF'
#!/bin/bash
if [ "$1" = "-l" ]; then exit 0; fi
cat > "$SMOKE_CRONTAB_OUT"
echo ok
EOF
  chmod +x "$TESTROOT/bin/systemctl" "$TESTROOT/bin/crontab"
  export SMOKE_CRONTAB_OUT="$TESTROOT/cron.txt"
  # 复制被测脚本（tests/unit/ 上两级 = 仓库根）
  REPO_ROOT="$(cd "$(dirname "${BATS_TEST_FILENAME:-$0}")/../.." && pwd)"
  cp "$REPO_ROOT/scripts/"*.sh "$REPO_ROOT/scripts/"*.py "$TESTROOT/repo/scripts/" 2>/dev/null || true
}

teardown() {
  rm -rf "$TESTROOT"
}

# ── 必填项校验（R15 修复：set -u 下 unbound → 友好报错）──

@test "必填校验：缺 PRIMARY_MAC_IP 友好报错" {
  cat > "$TESTROOT/repo/.env" <<'EOF'
OBSIDIAN_VAULT_PATH=$TESTROOT/vault
SSH_USER=test
EOF
  run env HOME="$TESTROOT/home" PATH="$TESTROOT/bin:$PATH" bash "$TESTROOT/repo/scripts/setup-server.sh"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "请填写 PRIMARY_MAC_IP"
}

@test "必填校验：缺 SSH_USER 友好报错" {
  cat > "$TESTROOT/repo/.env" <<'EOF'
OBSIDIAN_VAULT_PATH=$TESTROOT/vault
PRIMARY_MAC_IP=10.0.0.99
EOF
  run env HOME="$TESTROOT/home" PATH="$TESTROOT/bin:$PATH" bash "$TESTROOT/repo/scripts/setup-server.sh"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "请填写 SSH_USER"
}

@test "必填校验：.env 缺失时报错" {
  run env HOME="$TESTROOT/home" bash "$TESTROOT/repo/scripts/setup-server.sh"
  [ "$status" -eq 1 ]
  echo "$output" | grep -q "请先复制 .env.example"
}
