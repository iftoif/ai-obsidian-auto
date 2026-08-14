#!/usr/bin/env bash
# 节点自动发现：扫描 Vault/.hermes-nodes/ 注册标记，记录新机器 + 写文档 + 发通知 + 建立 SSH 信任
set -uo pipefail

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
    if [ -n "$NODE_PUBKEY" ] && [ "$NODE_PUBKEY" != "" ]; then
      if ! grep -qF "$NODE_PUBKEY" "$AUTH_KEYS" 2>/dev/null; then
        echo "$NODE_PUBKEY" >> "$AUTH_KEYS"
        chmod 600 "$AUTH_KEYS"
        echo "🔑 已建立 SSH 信任：$NODE_HOST 公钥已加入 authorized_keys" >> "$LOG"
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
