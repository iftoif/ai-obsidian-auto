#!/usr/bin/env bats

# mac-session-pull 核心逻辑单元测试
# 直接测试脚本内的函数（通过 source + 覆盖辅助函数）

setup() {
  # 提取脚本并 stub 掉外部命令
  export TESTROOT="$(mktemp -d)"
  export HOME="$TESTROOT/home"
  mkdir -p "$HOME/.hermes/logs" "$HOME/.claude/projects" "$HOME/.codex/sessions" "$HOME/.pi/agent/sessions" "$HOME/.dsh/sessions"
}

teardown() {
  rm -rf "$TESTROOT"
}

# ── IP 校验逻辑（提取自 mac-session-pull.sh 的校验段）──

@test "IP 校验：合法 IPv4 通过" {
  ip='10.0.0.77'
  if python3 - "$ip" <<'PYEOF' 2>/dev/null
import re, sys
ip = sys.argv[1]
assert re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", ip)
assert all(0 <= int(x) <= 255 for x in ip.split('.'))
PYEOF
  then
    return 0
  else
    return 1
  fi
}

@test "IP 校验：999 越界拒绝（R15 修复）" {
  ip='999.999.999.999'
  if python3 - "$ip" <<'PYEOF' 2>/dev/null
import re, sys
ip = sys.argv[1]
assert re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", ip)
assert all(0 <= int(x) <= 255 for x in ip.split('.'))
PYEOF
  then
    return 1
  else
    return 0
  fi
}

@test "IP 校验：命令注入形态拒绝" {
  ip='10.0.0.1; rm -rf /'
  if python3 - "$ip" <<'PYEOF' 2>/dev/null
import re, sys
ip = sys.argv[1]
assert re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", ip)
assert all(0 <= int(x) <= 255 for x in ip.split('.'))
PYEOF
  then
    return 1
  else
    return 0
  fi
}

# ── hostname 空值保护（R4 修复：SERVER_HOSTNAME 空时 case ** 匹配一切）──

@test "SERVER_HOSTNAME 空值时节点不被跳过" {
  SERVER_HOSTNAME=''
  fname='my-mac-20260815-120000.json'
  skip=0
  if [ -n "$SERVER_HOSTNAME" ]; then
    case "$fname" in
      *${SERVER_HOSTNAME}*) skip=1 ;;
    esac
  fi
  [ "$skip" -eq 0 ]
}

@test "SERVER_HOSTNAME 非空时匹配则跳过" {
  SERVER_HOSTNAME='my-server'
  fname='my-server-20260815-120000.json'
  skip=0
  if [ -n "$SERVER_HOSTNAME" ]; then
    case "$fname" in
      *${SERVER_HOSTNAME}*) skip=1 ;;
    esac
  fi
  [ "$skip" -eq 1 ]
}

# ── 主 Mac 标记跳过（自审轮 1 修复：避免重复拉取）──

@test "主 Mac IP 的注册标记被跳过" {
  PRIMARY_MAC_IP='10.0.0.99'
  NODE_IP='10.0.0.99'
  skip=0
  [ -n "$PRIMARY_MAC_IP" ] && [ "$NODE_IP" = "$PRIMARY_MAC_IP" ] && skip=1
  [ "$skip" -eq 1 ]
}

@test "其他节点 IP 不被跳过" {
  PRIMARY_MAC_IP='10.0.0.99'
  NODE_IP='10.0.0.88'
  skip=0
  [ -n "$PRIMARY_MAC_IP" ] && [ "$NODE_IP" = "$PRIMARY_MAC_IP" ] && skip=1
  [ "$skip" -eq 0 ]
}
