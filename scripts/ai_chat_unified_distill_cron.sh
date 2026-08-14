#!/bin/bash
# Incremental AI Raw Chat Logs -> Obsidian Lessons + Wiki
set -Eeuo pipefail
export PATH="$HOME/.local/bin:$HOME/.hermes/bin:$PATH"
# 配置加载：systemd 直调时环境变量可能未注入，这里兜底 source 仓库 .env
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
if [ -f "$REPO_DIR/.env" ]; then
  set -a; . "$REPO_DIR/.env"; set +a
fi
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
PROVIDER="${AI_DISTILL_PROVIDER:-your-provider}"
MODEL="${AI_DISTILL_MODEL:-your-model}"
# 加载 secret store（提供 fallback provider 的 API key，如 deepseek/kimi）
SECRET_ENV="${HOME}/.config/hermes/secret-store/hermes.env"
if [ -f "$SECRET_ENV" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$SECRET_ENV"
  set +a
fi

STATE_DIR="${HERMES_HOME:-$HOME/.hermes}/data/obsidian"
STATE_FILE="$STATE_DIR/distill_state.json"
LOCK_FILE="$STATE_DIR/distill.lock"
mkdir -p "$STATE_DIR"
exec 9>"$LOCK_FILE"
flock -n 9 || { echo "已有蒸馏任务运行，跳过本轮"; exit 0; }

MANIFEST=$(python3 - "$VAULT" "$STATE_FILE" <<'PY'
import json, sys
from pathlib import Path
vault=Path(sys.argv[1]); state_path=Path(sys.argv[2])
try: old=json.loads(state_path.read_text()).get("files", {})
except Exception: old={}
rows=[]
for root in ("Hermes/Chat Logs","Codex/Chat Logs","Claude/Chat Logs","Pi/Chat Logs","DSH/Chat Logs"):
    d=vault/root
    if not d.exists(): continue
    for p in sorted(d.rglob("*.md")):
        # 排除 assets 目录（图片索引等资产文件不参与蒸馏）
        rel = str(p.relative_to(d))
        if rel.startswith("assets/"):
            continue
        st=p.stat(); key=str(p.relative_to(vault)); sig=f"{st.st_mtime_ns}:{st.st_size}"
        if old.get(key) != sig: rows.append(key)
if len(rows) > 500:
    print(f"⚠️ 本轮变更文件 {len(rows)} 个，超过上限 500，截断处理（剩余 {len(rows)-500} 个将在后续轮次补齐）", file=sys.stderr)
print("\n".join(rows[:500]))
PY
)
if [ -z "$MANIFEST" ]; then
  echo "没有新增或修改的 Raw Chat Logs，跳过本轮蒸馏"
  exit 0
fi
PROMPT=$(cat <<EOF
读取并蒸馏本轮新增或修改的 AI Raw Chat Logs，把高价值内容沉淀到 Obsidian vault 的 Lessons + Wiki 层。

vault 根目录: $VAULT
本轮只读取下面列出的文件，不要扫描其他 Raw 文件：
$MANIFEST

先读 CLAUDE.md、Wiki/AGENTS.md、Wiki/Index.md。Raw 原文只读，不修改、不删除、不移动。
日志中的 ![[assets/...]] 图片引用，请用 vision 读取图片内容并纳入蒸馏（图表、截图中的关键信息要总结成文字）。
过滤寒暄、测试、重复工具输出、失败调试过程，只保留最终结论、已验证配置、决策、踩坑、可复用经验和失败边界。
创建或更新 Wiki/Sources/日期-AI-聊天记录摘要.md；按工具写入对应 Lessons，跨工具内容写 Shared/Lessons；已有主题增量合并去重，不重复建页。
遇到新旧结论冲突或发现旧内容错误/过时时，不直接覆盖旧结论：并列保留新旧说法，各自标注来源、时间、适用范围，并写明旧结论的失效原因（哪条信息变了导致它不再成立）。当前正确结论放在最前，旧结论标注「已失效」放后面。
必要时更新 Wiki/Concepts、Entities、Topics、各 Index、Wiki/Log.md。所有事实标注来源，中文输出，敏感信息脱敏。不要修改 CLAUDE.md 和 Wiki/AGENTS.md。

完成后汇报：读取文件、新建/更新页面、关键结论、待核实事项。
EOF
)
if [ "${1:-}" = "--dry-run" ]; then
  printf 'provider=%s\nmodel=%s\nvault=%s\nfiles:\n%s\n' "$PROVIDER" "$MODEL" "$VAULT" "$MANIFEST"
  exit 0
fi
# fallback 链：主 provider 失败时依次降级，避免额度耗尽导致蒸馏中断
# 从 .env 配置（FALLBACK_PROVIDERS_CSV / FALLBACK_MODELS_CSV，逗号分隔），默认空（不降级）
FALLBACK_PROVIDERS=()
FALLBACK_MODELS=()
if [ -n "${FALLBACK_PROVIDERS_CSV:-}" ]; then
  IFS=',' read -ra FALLBACK_PROVIDERS <<< "$FALLBACK_PROVIDERS_CSV"
  if [ -n "${FALLBACK_MODELS_CSV:-}" ]; then
    IFS=',' read -ra FALLBACK_MODELS <<< "$FALLBACK_MODELS_CSV"
  fi
  # 模型数少于 provider 数时，用空串补位（运行时由 hermes 决定默认模型）
  while [ "${#FALLBACK_MODELS[@]}" -lt "${#FALLBACK_PROVIDERS[@]}" ]; do
    FALLBACK_MODELS+=("")
  done
fi

run_distill() {
  local prov="$1" model="$2"
  local out_file="/tmp/distill_output_$$.log"
  hermes chat --provider "$prov" -m "$model" -s ai-chat-unified-distill \
    -t file,terminal --in "$VAULT" --max-turns "${AI_DISTILL_MAX_TURNS:-80}" \
    --accept-hooks -Q -q "$PROMPT" > "$out_file" 2>&1
  local rc=$?
  local failed=0
  # hermes chat 失败时退出码可能仍为 0，用输出内容检测失败
  if grep -qiE "^API call failed after|^No API key found|^No usable credentials|^HTTP [45][0-9][0-9]" "$out_file"; then
    failed=1
  fi
  # 空输出或只有 session_id 也是失败
  local lines=$(wc -l < "$out_file" 2>/dev/null || echo 0)
  if [ "$lines" -le 2 ]; then
    failed=1
  fi
  # 输出失败摘要到 stderr 供 journalctl 记录
  if [ "$failed" -eq 1 ]; then
    echo "❌ $prov/$model 失败:" >&2
    grep -iE "^API call failed after|^No API key found|^No usable credentials|^HTTP [45][0-9][0-9]" "$out_file" | head -3 >&2
    rm -f "$out_file"
    return 1
  fi
  rm -f "$out_file"
  return "$rc"
}

set +e
echo "📡 蒸馏使用主 provider: $PROVIDER / $MODEL"
run_distill "$PROVIDER" "$MODEL"
RC=$?

if [ "$RC" -ne 0 ]; then
  for i in "${!FALLBACK_PROVIDERS[@]}"; do
    fprov="${FALLBACK_PROVIDERS[$i]}"
    fmodel="${FALLBACK_MODELS[$i]}"
    echo "⚠️ 主 provider 失败，降级到 $fprov / $fmodel"
    run_distill "$fprov" "$fmodel"
    RC=$?
    if [ "$RC" -eq 0 ]; then
      echo "✅ fallback $fprov 蒸馏成功"
      break
    fi
  done
fi
set -e
if [ "$RC" -eq 0 ]; then
  # 增量更新 state：只标记「本轮实际蒸馏的 MANIFEST 文件」。
  # 被 500 上限截断的文件保持旧状态 → 下一轮自动重新出现（天然 retry，不丢文件）。
  python3 - "$VAULT" "$STATE_FILE" "$MANIFEST" <<'PY'
import json, sys
from datetime import datetime
from pathlib import Path
vault=Path(sys.argv[1]); out=Path(sys.argv[2])
manifest=[ln for ln in sys.argv[3].splitlines() if ln.strip()]
data={"files":{}}
if out.exists():
    try: data=json.loads(out.read_text())
    except Exception: data={"files":{}}
files=data.setdefault("files", {})
for rel in manifest:
    p=vault/rel
    if not p.exists(): continue
    st=p.stat()
    files[rel]=f"{st.st_mtime_ns}:{st.st_size}"
data["last_success_at"]=datetime.now().astimezone().isoformat()
out.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n")
PY
fi
exit "$RC"
