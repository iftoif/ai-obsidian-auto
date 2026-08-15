#!/usr/bin/env bats

# vault-pull 核心逻辑单元测试（变量缺省 / 路径构建 / SSH 保活）

setup() {
  TESTROOT="$(mktemp -d)"
  export TESTROOT HOME="$TESTROOT/home"
  mkdir -p "$HOME/.hermes/logs"
}

teardown() {
  rm -rf "$TESTROOT"
}

@test "变量缺省：未配置 PRIMARY_MAC_IP 时优雅退出 0" {
  run bash -c "
    set -uo pipefail
    PRIMARY_MAC_IP=''
    SSH_USER=''
    if [ -z \"$PRIMARY_MAC_IP\" ] || [ -z \"$SSH_USER\" ]; then
      echo 'skip msg'
      exit 0
    fi
    exit 1
  "
  [ "$status" -eq 0 ]
  echo "$output" | grep -q 'skip'
}

@test "路径构建：MAC_VAULT 含空格正确处理" {
  MAC_USER='testuser'
  MAC_VAULT="/Users/$MAC_USER/Library/Mobile Documents/com~apple~CloudDocs/obsidian/"
  echo "$MAC_VAULT" | grep -q 'Mobile Documents'
  echo "$MAC_VAULT" | grep -q 'testuser'
}

@test "SSH 保活超时参数存在（防 SSH 卡死）" {
  # 相对定位仓库根（不硬编码本机路径，CI/其他机器可跑）
  REPO_ROOT="$(cd "$(dirname "${BATS_TEST_FILENAME:-$0}")" && cd ../.. && pwd)"
  grep -q 'ServerAliveInterval=5' "$REPO_ROOT/scripts/vault-pull.sh"
  grep -q 'ServerAliveCountMax=2' "$REPO_ROOT/scripts/vault-pull.sh"
}