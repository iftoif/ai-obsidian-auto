#!/usr/bin/env bash
# 节点自动发现：扫描 Vault/.hermes-nodes/ 注册标记，记录新机器 + 写文档 + 发通知 + 建立 SSH 信任
#
# ⚠️ 安全警示（有意设计，请读后再部署）：
#   本脚本会自动把注册标记里的 ssh_pubkey 加入 authorized_keys，实现新机器「零人工」接入。
#   设计前提：**所有能写入 Vault/.hermes-nodes/ 的设备/账号都是你信任的**（家庭内网 + 个人 iCloud）。
#   风险：若你的 iCloud 账号被盗、或 Vault 所在目录被第三方 App 写入，攻击者投递一个含自己公钥的
#         json 即可 SSH 登录本服务器。
#   缓解：见 docs/security.md「自动信任的设计边界」（iCloud 双重认证 / 不共享 Vault 给第三方 App /
#         定期检查 .hermes-nodes 目录）。
#         不想要自动信任：注释掉下方「建立 SSH 信任」代码块，改为人工执行
#            echo "<公钥>" >> ~/.ssh/authorized_keys
set -uo pipefail

# authorized_keys 写入加固：umask 077（新文件默认仅本人可读写）
umask 077


# 配置兜底：优先环境变量（systemd 注入），回退 source 仓库 .env（手工部署路径）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$REPO_DIR/.env" ]; then
  set -a; . "$REPO_DIR/.env"; set +a
fi

VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
NODES_DIR="$VAULT/.hermes-nodes"
REGISTRY="$HOME/.hermes/data/nodes-registry.json"
LOG="$HOME/.hermes/logs/node-discovery.log"
HERMES_SEND="$HOME/.hermes/hermes-agent/venv/bin/hermes"
AUTH_KEYS="$HOME/.ssh/authorized_keys"

mkdir -p "$(dirname "$LOG")" "$(dirname "$REGISTRY")" "$HOME/.ssh"

# 读取已登记节点
if [ -f "$REGISTRY" ]; then
  KNOWN=$(python3 -c 'import json; d=json.load(open("'"$REGISTRY"'")); print("\n".join(d.get("nodes",{}).keys()))' 2>/dev/null || echo "")
else
  KNOWN=""
fi

# 扫描注册标记
NEW_FOUND=0
if [ -d "$NODES_DIR" ]; then
  for f in "$NODES_DIR"/*.json; do
    [ -f "$f" ] || continue
    fname=$(basename "$f")
    # 注册源完整性校验 1：文件名白名单（<hostname>-<YYYYMMDD-HHMMSS>.json）
    # 拒绝不符合「本系统报到模板」命名约定的文件（防止无关文件被误当节点）
    if ! echo "$fname" | grep -Eq '^[A-Za-z0-9_.-]+-[0-9]{8}-[0-9]{6}\.json$'; then
      echo "⚠️ 跳过非标准命名的注册文件: $fname" >> "$LOG"
      continue
    fi
    # 注册源完整性校验 2：JSON 严格解析 + 必填字段类型/长度/格式
    # role 白名单可配置：NODE_ROLE_ALLOWLIST="workstation server ro"（空格分隔）
    if ! python3 - "$f" "${NODE_ROLE_ALLOWLIST:-workstation server ro}" <<'PYEOF' 2>/dev/null
import json, re, sys, os
d = json.load(open(sys.argv[1]))
roles = set(sys.argv[2].split())
assert isinstance(d.get("hostname", ""), str) and 1 <= len(d["hostname"]) <= 64, "bad hostname"
assert d.get("role") in roles, "bad role"
ip = d.get("lan_ip", "")
assert re.fullmatch(r"(\d{1,3}\.){3}\d{1,3}", ip), "bad lan_ip"
assert all(0 <= int(x) <= 255 for x in ip.split(".")), "lan_ip octet out of range"
assert re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", d.get("hostname", "")), "bad hostname charset"
if "ssh_pubkey" in d:
    assert isinstance(d["ssh_pubkey"], str) and 1 <= len(d["ssh_pubkey"]) <= 512, "bad pubkey"
if "user" in d:
    assert isinstance(d["user"], str) and 1 <= len(d["user"]) <= 64, "bad user"
PYEOF
then
      echo "⚠️ 跳过字段校验失败的注册文件: $fname" >> "$LOG"
      continue
    fi
    # 已登记的跳过
    if echo "$KNOWN" | grep -qF "$fname"; then
      continue
    fi

    # 新节点：记录日志
    echo "=== $(date +%F_%T) 发现新节点: $fname ===" >> "$LOG"
    cat "$f" >> "$LOG"

    # 解析节点信息
    NODE_HOST=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("hostname","unknown"))' 2>/dev/null)
    NODE_ROLE=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("role","unknown"))' 2>/dev/null)
    NODE_OS=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("os","unknown"))' 2>/dev/null)
    NODE_AT=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("joined_at","unknown"))' 2>/dev/null)
    NODE_IP=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("lan_ip",""))' 2>/dev/null)
    NODE_PUBKEY=$(python3 -c 'import json; print(json.load(open("'"$f"'")).get("ssh_pubkey",""))' 2>/dev/null)

    # 建立 SSH 信任（公钥加 authorized_keys，服务器可主动配置新机器）
    # 公钥校验：1) 必须单行（拒绝换行注入）2) ssh-keygen 实测可解析
    # （支持 rsa/ed25519/ecdsa/sk-*/cert-* 全部 OpenSSH 类型，比正则 allowlist 更兼容）
    if [ -n "$NODE_PUBKEY" ] && [ "$NODE_PUBKEY" != "" ]; then
      if [ "$(printf '%s\n' "$NODE_PUBKEY" | wc -l | tr -d ' ')" -eq 1 ] && \
         printf '%s\n' "$NODE_PUBKEY" | ssh-keygen -lf - >/dev/null 2>&1; then
        # 并发一致性：flock 保护 authorized_keys 读写（防多实例同时写）
        (
          flock -x 200
          if ! grep -qF "$NODE_PUBKEY" "$AUTH_KEYS" 2>/dev/null; then
            echo "$NODE_PUBKEY" >> "$AUTH_KEYS"
            echo "🔑 已建立 SSH 信任：$NODE_HOST 公钥已加入 authorized_keys" >> "$LOG"
          fi
          # 权限断言：无论是否新写，保证权限正确
          chmod 600 "$AUTH_KEYS"
          chmod 700 "$HOME/.ssh"
        ) 200>"$AUTH_KEYS.lock"
      else
        echo "⚠️ 拒绝非法公钥（格式校验失败）：$NODE_HOST" >> "$LOG"
      fi
    fi

    # 主动写节点文档到 Wiki/Entities/
    ENT_DIR="$VAULT/Wiki/Entities"
    mkdir -p "$ENT_DIR"
    ENT_FILE="$ENT_DIR/节点-${NODE_HOST}.md"
    cat > "$ENT_FILE" << ENTEOF
---
title: 节点 ${NODE_HOST}
type: entity
tags:
  - node
  - machine
created: $(date +%Y-%m-%d)
---

# 节点 ${NODE_HOST}

| 属性 | 值 |
|------|-----|
| 主机名 | ${NODE_HOST} |
| 角色 | ${NODE_ROLE} |
| 系统 | ${NODE_OS} |
| 局域网 IP | ${NODE_IP:-未知} |
| 加入时间 | ${NODE_AT} |
| SSH 信任 | $( [ -n "$NODE_PUBKEY" ] && [ "$NODE_PUBKEY" != "" ] && echo "已建立" || echo "未建立" ) |

> 由 node-discovery 自动登记（$(date +%F_%T)）
ENTEOF
    echo "📄 已写节点文档: $ENT_FILE" >> "$LOG"

    # 主动发 Telegram 通知
    echo "🖥️ 新机器加入生态：${NODE_HOST}（${NODE_ROLE}）
系统：${NODE_OS}
IP：${NODE_IP:-未知}
SSH 信任：$( [ -n "$NODE_PUBKEY" ] && [ "$NODE_PUBKEY" != "" ] && echo "已建立" || echo "未建立" )" | "$HERMES_SEND" send -t telegram >> "$LOG" 2>&1
    echo "📡 已发 Telegram 通知" >> "$LOG"

    NEW_FOUND=1
  done
fi

# 更新登记表
if [ "$NEW_FOUND" -eq 1 ] || [ ! -f "$REGISTRY" ]; then
  python3 - "$VAULT" "$REGISTRY" << 'PYEOF'
import json, sys, glob, os, datetime
vault = sys.argv[1]
registry = sys.argv[2]
nodes_dir = os.path.join(vault, ".hermes-nodes")
nodes = {}
if os.path.exists(registry):
    try:
        nodes = json.load(open(registry)).get("nodes", {})
    except Exception:
        nodes = {}
for f in glob.glob(os.path.join(nodes_dir, "*.json")):
    name = os.path.basename(f)
    try:
        data = json.load(open(f))
    except Exception:
        continue
    nodes[name] = data
json.dump({"nodes": nodes, "updated_at": datetime.datetime.now().isoformat()},
          open(registry, "w"), ensure_ascii=False, indent=2)
print(f"登记表已更新：{len(nodes)} 个节点")
PYEOF
fi

if [ "$NEW_FOUND" -eq 1 ]; then
  echo "✅ 发现新节点，已记录 + SSH 信任 + 写文档 + 通知" >> "$LOG"
fi
exit 0
