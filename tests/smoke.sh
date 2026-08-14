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
grep -q "部署完成" "$TESTROOT/setup.log" && ok "打印部署完成" || bad "未打印部署完成"
[ -f "$TESTROOT/crontab-received.txt" ] && grep -q "export-all.sh" "$TESTROOT/crontab-received.txt" && ok "crontab 收到 export-all 调度" || bad "crontab 未收到 export-all"
UNIT_COUNT=$(ls "$TESTROOT/home/.config/systemd/user/"*.service 2>/dev/null | wc -l | tr -d ' ')
[ "$UNIT_COUNT" -eq 8 ] && ok "8 个 service 生成（实得 $UNIT_COUNT）" || bad "service 数不对（实得 $UNIT_COUNT，应为 8）"
grep -q "ExecStart=$TESTROOT/repo/scripts/vault-pull.sh" "$TESTROOT/home/.config/systemd/user/vault-pull.service" && ok "ExecStart 指向活代码路径" || bad "ExecStart 路径不对"
grep -q "FALLBACK_PROVIDERS_CSV=deepseek" "$TESTROOT/home/.config/systemd/user/obsidian-server-distill.service" && ok "蒸馏 service 注入 fallback" || bad "fallback 未注入"

# ── 2. wiki_git_autocommit 全新部署（部分目录缺失场景）──
step "2. wiki_git_autocommit 首次提交"
mkdir -p "$TESTROOT/vault/Wiki" && echo "# 测试笔记" > "$TESTROOT/vault/Wiki/note1.md"
if HOME="$TESTROOT/home" OBSIDIAN_VAULT_PATH="$TESTROOT/vault" WIKI_REPO="$TESTROOT/home/obsidian-wiki" HERMES_HOME="$TESTROOT/home/.hermes" bash "$REPO/scripts/wiki_git_autocommit.sh" 2>"$TESTROOT/auto.err"; then
  ok "autocommit exit 0"
else
  bad "autocommit 失败"; cat "$TESTROOT/auto.err"
fi
git -C "$TESTROOT/home/obsidian-wiki" log --oneline >/dev/null 2>&1 && ok "首次提交成功" || bad "无提交记录"
git -C "$TESTROOT/home/obsidian-wiki" ls-files | grep -q "Wiki/note1.md" && ok "Wiki/note1.md 已入库" || bad "note1.md 未入库"

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
grep -q "$PUB" "$TESTROOT/home/.ssh/authorized_keys" 2>/dev/null && ok "合法公钥自动信任" || bad "合法公钥未信任"
grep -q "evil" "$TESTROOT/home/.ssh/authorized_keys" 2>/dev/null && bad "非法节点被信任" || ok "非法节点被拒"

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