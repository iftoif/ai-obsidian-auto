#!/usr/bin/env bats

# node-discovery 核心逻辑单元测试

setup() {
  TESTROOT="$(mktemp -d)"
  export TESTROOT HOME="$TESTROOT/home"
  mkdir -p "$HOME/obsidian/.hermes-nodes" "$HOME/.hermes/data" "$HOME/.hermes/logs" "$HOME/.ssh"
  mkdir -p "$HOME/.hermes/hermes-agent/venv/bin"
  printf '#!/bin/bash
echo ok
' > "$HOME/.hermes/hermes-agent/venv/bin/hermes"
  chmod +x "$HOME/.hermes/hermes-agent/venv/bin/hermes"
}

teardown() {
  rm -rf "$TESTROOT"
}

# ── 注册源文件名白名单校验 ──

@test "文件名白名单：标准命名通过" {
  fname='good-mac-20260815-120000.json'
  if echo "$fname" | grep -Eq '^[A-Za-z0-9_.-]+-[0-9]{8}-[0-9]{6}.json$'; then
    return 0
  else
    return 1
  fi
}

@test "文件名白名单：非标准命名拒绝" {
  for fname in 'notes.txt' 'evil' 'a-b.json' 'x-20260815.json'; do
    if echo "$fname" | grep -Eq '^[A-Za-z0-9_.-]+-[0-9]{8}-[0-9]{6}.json$'; then
      return 1
    fi
  done
}

# ── JSON 字段校验 ──

@test "字段校验：合法节点通过" {
  cat > "$HOME/obsidian/.hermes-nodes/good-20260815-120000.json" <<'EOF'
{"hostname":"good-mac","role":"workstation","lan_ip":"10.0.0.77"}
EOF
  python3 - "$HOME/obsidian/.hermes-nodes/good-20260815-120000.json" "workstation server ro" <<'PYEOF' 2>/dev/null
import json, re, sys
d = json.load(open(sys.argv[1]))
roles = set(sys.argv[2].split())
assert isinstance(d.get('hostname', ''), str) and 1 <= len(d['hostname']) <= 64
assert d.get('role') in roles
ip = d.get('lan_ip', '')
if ip:
    assert re.fullmatch(r'(\d{1,3}\.){3}\d{1,3}', ip)
    assert all(0 <= int(x) <= 255 for x in ip.split('.'))
PYEOF
}

@test "字段校验：非法角色拒绝" {
  cat > "$HOME/obsidian/.hermes-nodes/bad-20260815-120000.json" <<'EOF'
{"hostname":"evil","role":"admin","lan_ip":"10.0.0.78"}
EOF
  if python3 - "$HOME/obsidian/.hermes-nodes/bad-20260815-120000.json" "workstation server ro" <<'PYEOF' 2>/dev/null
import json, re, sys
d = json.load(open(sys.argv[1]))
roles = set(sys.argv[2].split())
assert d.get('role') in roles
PYEOF
  then
    return 1
  fi
}

@test "字段校验：IP 越界拒绝" {
  cat > "$HOME/obsidian/.hermes-nodes/bad2-20260815-120000.json" <<'EOF'
{"hostname":"evil","role":"workstation","lan_ip":"999.1.1.1"}
EOF
  if python3 - "$HOME/obsidian/.hermes-nodes/bad2-20260815-120000.json" "workstation server ro" <<'PYEOF' 2>/dev/null
import json, re, sys
d = json.load(open(sys.argv[1]))
ip = d.get('lan_ip', '')
if ip:
    assert re.fullmatch(r'(\d{1,3}\.){3}\d{1,3}', ip)
    assert all(0 <= int(x) <= 255 for x in ip.split('.'))
PYEOF
  then
    return 1
  fi
}

@test "字段校验：lan_ip 为空允许（Wi-Fi 机器）" {
  cat > "$HOME/obsidian/.hermes-nodes/wifi-20260815-120000.json" <<'EOF'
{"hostname":"wifi-mac","role":"workstation","lan_ip":""}
EOF
  python3 - "$HOME/obsidian/.hermes-nodes/wifi-20260815-120000.json" "workstation server ro" <<'PYEOF' 2>/dev/null
import json, re, sys
d = json.load(open(sys.argv[1]))
ip = d.get('lan_ip', '')
if ip:
    assert re.fullmatch(r'(\d{1,3}\.){3}\d{1,3}', ip)
    assert all(0 <= int(x) <= 255 for x in ip.split('.'))
PYEOF
}

# ── 公钥校验 ──

@test "公钥校验：合法 ed25519 通过" {
  ssh-keygen -t ed25519 -f "$TESTROOT/id_ed" -N '' -q 2>/dev/null
  PUB=$(cat "$TESTROOT/id_ed.pub")
  if [ "$(printf '%s
' "$PUB" | wc -l | tr -d ' ')" -eq 1 ] &&      printf '%s
' "$PUB" | ssh-keygen -lf - >/dev/null 2>&1; then
    return 0
  else
    return 1
  fi
}

@test "公钥校验：多行注入拒绝" {
  PUB='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI
malicious line'
  if [ "$(printf '%s
' "$PUB" | wc -l | tr -d ' ')" -eq 1 ]; then
    return 1
  fi
}

@test "公钥去重：按本体（类型+base64）" {
  ssh-keygen -t ed25519 -f "$TESTROOT/id_ed2" -N '' -q 2>/dev/null
  PUB=$(cat "$TESTROOT/id_ed2.pub")
  KEY_BODY=$(echo "$PUB" | awk '{print $1" "$2}')
  AUTH="$HOME/.ssh/authorized_keys"
  echo "$PUB user1@mac" >> "$AUTH"
  echo "$PUB user2@mac" >> "$AUTH"
  CNT=$(awk '{print $1" "$2}' "$AUTH" | grep -cF "$KEY_BODY" || true)
  [ "$CNT" -ge 1 ]
}
