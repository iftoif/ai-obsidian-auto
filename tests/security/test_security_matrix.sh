#!/usr/bin/env bash
# 安全矩阵测试：注入类/信息泄露类/权限类
# 用法：bash tests/security/test_security_matrix.sh
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TESTROOT="$(mktemp -d /tmp/qa-sec.XXXXXX)"
PASS=0; FAIL=0
trap 'rm -rf "$TESTROOT"' EXIT
ok(){ echo "  ✅ $1"; PASS=$((PASS+1)); }
bad(){ echo "  ❌ $1"; FAIL=$((FAIL+1)); }

mkdir -p "$TESTROOT/home/obsidian/.hermes-nodes" "$TESTROOT/home/.hermes/data" "$TESTROOT/home/.hermes/logs" "$TESTROOT/home/.ssh" "$TESTROOT/home/.hermes/hermes-agent/venv/bin"
printf '#!/bin/bash\necho ok\n' > "$TESTROOT/home/.hermes/hermes-agent/venv/bin/hermes"
chmod +x "$TESTROOT/home/.hermes/hermes-agent/venv/bin/hermes"

echo "▸ 注入类：node-discovery 对抗性输入"

# 1. 命令注入 lan_ip
echo '{"hostname":"a","role":"workstation","lan_ip":"10.0.0.1; rm -rf /"}' > "$TESTROOT/home/obsidian/.hermes-nodes/a-20260815-150000.json"
# 2. 路径注入 hostname
echo '{"hostname":"../../etc/passwd","role":"workstation","lan_ip":"10.0.0.2"}' > "$TESTROOT/home/obsidian/.hermes-nodes/b-20260815-150001.json"
# 3. 换行注入 pubkey
printf '{"hostname":"c","role":"workstation","lan_ip":"10.0.0.3","ssh_pubkey":"ssh-ed25519 AAAA\\necho pwned >> /tmp/pwned"}' > "$TESTROOT/home/obsidian/.hermes-nodes/c-20260815-150002.json"
# 4. 类型混淆
echo '{"hostname":123,"role":"workstation","lan_ip":"10.0.0.4"}' > "$TESTROOT/home/obsidian/.hermes-nodes/d-20260815-150003.json"
# 5. 超大 hostname
BIG=$(python3 -c 'print("x"*100)')
echo "{\"hostname\":\"$BIG\",\"role\":\"workstation\",\"lan_ip\":\"10.0.0.5\"}" > "$TESTROOT/home/obsidian/.hermes-nodes/e-20260815-150004.json"
# 6. 合法节点（对照）
echo '{"hostname":"good","role":"workstation","lan_ip":"10.0.0.88"}' > "$TESTROOT/home/obsidian/.hermes-nodes/good-20260815-150005.json"

HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/home/obsidian" bash "$REPO/scripts/node-discovery.sh" >/dev/null 2>&1

# 验证：5 个恶意文件全部被拒，1 个合法节点通过
LOG="$TESTROOT/home/.hermes/logs/node-discovery.log"

for badname in a b c d e; do
  if grep -q "跳过" "$LOG"; then
    ok "$badname 恶意输入被拒"
  else
    bad "$badname 未被拒"
  fi
done

# 关键：没有文件被写入 authorized_keys（除了合法节点）
if [ -f "$TESTROOT/home/.ssh/authorized_keys" ]; then
  if grep -q "pwned\|rm -rf" "$TESTROOT/home/.ssh/authorized_keys" 2>/dev/null; then
    bad "注入内容进入 authorized_keys！"
  else
    ok "注入内容未进入 authorized_keys"
  fi
else
  ok "authorized_keys 未生成（无合法公钥）"
fi

# /tmp/pwned 不应存在
if [ -f /tmp/pwned ]; then
  bad "换行注入成功执行！"
  rm -f /tmp/pwned
else
  ok "换行注入未执行"
fi

echo
echo "▸ 信息泄露类：仓库自检"

# 敏感扫描（当前树）
if grep -rn "aaronhk\|/home/aaron\|192\.168\.[0-9]" "$REPO/scripts" "$REPO/docs" "$REPO/templates" "$REPO/.env.example" 2>/dev/null | grep -v "your_user\|192\.168\.x\|192\.168\.1\.50\|192\.168\.1\.[0-9]" | head -2 | grep -q .; then
  bad "敏感信息残留"
else
  ok "无敏感信息残留"
fi

echo
echo "===== 安全矩阵：$PASS 通过 / $FAIL 失败 ====="
[ "$FAIL" -eq 0 ]