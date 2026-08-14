#!/usr/bin/env bash
# 冒烟测试：在沙箱里端到端跑核心链路，验证 setup-server / autocommit / 导出 不回归。
# 用法：bash tests/smoke.sh（无需 root，不碰真实 systemd/crontab/vault）
# 依赖：bash / python3 / git / ssh-keygen
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TESTROOT="$(mktemp -d /tmp/ai-obsidian-auto-smoke.XXXXXX)"
PASS=0
FAIL=0

cleanup() { rm -rf "$TESTROOT"; }
trap cleanup EXIT

step() { echo; echo "▸ $1"; }
ok()   { echo "  ✅ $1"; PASS=$((PASS+1)); }
bad()  { echo "  ❌ $1"; FAIL=$((FAIL+1)); }

# 准备沙箱
mkdir -p "$TESTROOT/repo" "$TESTROOT/bin" "$TESTROOT/home/.config/systemd/user"
cp -r "$REPO/scripts" "$TESTROOT/repo/scripts"

# stub systemctl / crontab（crontab -l 模拟空 crontab，捕获写入内容）
printf '#!/bin/bash\necho "[systemctl] $*"\n' > "$TESTROOT/bin/systemctl"
cat > "$TESTROOT/bin/crontab" <<'EOF'
#!/bin/bash
if [ "$1" = "-l" ]; then exit 0; fi
cat > "$SMOKE_CRONTAB_OUT"
echo "[crontab 写入]"
EOF
chmod +x "$TESTROOT/bin/systemctl" "$TESTROOT/bin/crontab"
export SMOKE_CRONTAB_OUT="$TESTROOT/crontab-received.txt"

cat > "$TESTROOT/repo/.env" <<EOF
SERVER_USER=tester
SERVER_HOSTNAME=smoke-server
OBSIDIAN_VAULT_PATH=$TESTROOT/vault
HERMES_HOME=$TESTROOT/home/.hermes
PRIMARY_MAC_IP=10.0.0.99
SSH_USER=testermac
MAC_USER=testermac
AI_DISTILL_PROVIDER=openai-codex
AI_DISTILL_MODEL=gpt-5.6-luna
FALLBACK_PROVIDERS_CSV=deepseek
FALLBACK_MODELS_CSV=deepseek-v4-flash
EOF

# ── 1. setup-server 全新部署（空 crontab 场景，曾有多轮 bug）──
step "1. setup-server 全新部署"
if HOME="$TESTROOT/home" PATH="$TESTROOT/bin:$PATH" bash "$TESTROOT/repo/scripts/setup-server.sh" >"$TESTROOT/setup.log" 2>&1; then
  ok "setup-server exit 0"
else
  bad "setup-server 失败（应 exit 0）"; tail -5 "$TESTROOT/setup.log"
fi
if grep -q "部署完成" "$TESTROOT/setup.log"; then ok "打印部署完成"; else bad "未打印部署完成"; fi
if [ -f "$TESTROOT/crontab-received.txt" ] && grep -q "export-all.sh" "$TESTROOT/crontab-received.txt"; then
  ok "crontab 收到 export-all 调度"
else
  bad "crontab 未收到 export-all"
fi
UNIT_COUNT=$(find "$TESTROOT/home/.config/systemd/user" -maxdepth 1 -name '*.service' 2>/dev/null | wc -l | tr -d ' ')
if [ "$UNIT_COUNT" -eq 8 ]; then
  ok "8 个 service 生成（实得 ${UNIT_COUNT}）"
else
  bad "service 数不对（实得 ${UNIT_COUNT}，应为 8）"
fi
if grep -q "ExecStart=$TESTROOT/repo/scripts/vault-pull.sh" "$TESTROOT/home/.config/systemd/user/vault-pull.service"; then
  ok "ExecStart 指向活代码路径"
else
  bad "ExecStart 路径不对"
fi
if grep -q "FALLBACK_PROVIDERS_CSV=deepseek" "$TESTROOT/home/.config/systemd/user/obsidian-server-distill.service"; then
  ok "蒸馏 service 注入 fallback"
else
  bad "fallback 未注入"
fi

# ── 2. wiki_git_autocommit 全新部署（部分目录缺失场景）──
step "2. wiki_git_autocommit 首次提交"
mkdir -p "$TESTROOT/vault/Wiki" && echo "# 测试笔记" > "$TESTROOT/vault/Wiki/note1.md"
if HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" WIKI_REPO="$TESTROOT/home/obsidian-wiki" HERMES_HOME="$TESTROOT/home/.hermes" bash "$REPO/scripts/wiki_git_autocommit.sh" 2>"$TESTROOT/auto.err"; then
  ok "autocommit exit 0"
else
  bad "autocommit 失败"; cat "$TESTROOT/auto.err"
fi
if git -C "$TESTROOT/home/obsidian-wiki" log --oneline >/dev/null 2>&1; then
  ok "首次提交成功"
else
  bad "无提交记录"
fi
if git -C "$TESTROOT/home/obsidian-wiki" ls-files | grep -q "Wiki/note1.md"; then
  ok "Wiki/note1.md 已入库"
else
  bad "note1.md 未入库"
fi

# ── 3. node-discovery 注册源校验（好/坏文件）──
step "3. node-discovery 校验"
mkdir -p "$TESTROOT/vault/.hermes-nodes" "$TESTROOT/home/.hermes/hermes-agent/venv/bin"
printf '#!/bin/bash\necho ok\n' > "$TESTROOT/home/.hermes/hermes-agent/venv/bin/hermes"
chmod +x "$TESTROOT/home/.hermes/hermes-agent/venv/bin/hermes"
ssh-keygen -t ed25519 -f "$TESTROOT/id_ed" -N '' -q
PUB=$(cat "$TESTROOT/id_ed.pub")
cat > "$TESTROOT/vault/.hermes-nodes/good-mac-20260815-120000.json" <<EOF
{"hostname":"good-mac","role":"workstation","lan_ip":"10.0.0.77","ssh_pubkey":"$PUB"}
EOF
echo '{"hostname":"evil","role":"admin","lan_ip":"999.1.1.1"}' > "$TESTROOT/vault/.hermes-nodes/evil-20260815-120001.json"
HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" bash "$REPO/scripts/node-discovery.sh" >/dev/null 2>&1
if grep -q "$PUB" "$TESTROOT/home/.ssh/authorized_keys" 2>/dev/null; then
  ok "合法公钥自动信任"
else
  bad "合法公钥未信任"
fi
if grep -q "evil" "$TESTROOT/home/.ssh/authorized_keys" 2>/dev/null; then
  bad "非法节点被信任"
else
  ok "非法节点被拒"
fi

# ── 3.5 .env.example 可被 source（防回归：尖括号占位符被 bash 当重定向）──
step "3.5 .env.example source 检查"
if bash -c 'set -e; source "'"$REPO/.env.example"'"; true' 2>/dev/null; then
  ok ".env.example 可 source（无语法错误）"
else
  bad ".env.example source 失败（占位符含未加引号的特殊字符）"
fi

# ── 4. Python 语法 ──
step "4. Python 语法编译"
if python3 -m py_compile "$REPO"/scripts/*.py; then
  ok "全部 .py 可编译"
else
  bad "有 .py 编译失败"
fi

echo
echo "===== 冒烟测试结果：$PASS 通过 / $FAIL 失败 ====="
[ "$FAIL" -eq 0 ]