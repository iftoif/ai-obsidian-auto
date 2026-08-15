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
PROVIDER="${AI_DISTILL_PROVIDER:-openai-codex}"
MODEL="${AI_DISTILL_MODEL:-gpt-5.6-luna}"

# ── provider 能力矩阵（按 provider 能力动态调整蒸馏行为）──
# 列表逗号分隔，provider 名精确匹配（hermes --provider 参数值）
VISION_PROVIDERS="${AI_DISTILL_VISION_PROVIDERS:-openai-codex,glm-4v,glm-4v-flash,gemini,gpt-4o}"
LONG_CONTEXT_PROVIDERS="${AI_DISTILL_LONG_CONTEXT_PROVIDERS:-openai-codex,gemini,claude}"
TOOL_USE_PROVIDERS="${AI_DISTILL_TOOL_USE_PROVIDERS:-openai-codex,claude}"
MULTILINGUAL_PROVIDERS="${AI_DISTILL_MULTILINGUAL_PROVIDERS:-openai-codex,deepseek,kimi,glm-4v,glm-4v-flash,gemini}"
# 长上下文 provider 的 manifest 上限（普通 500，长上下文 1500）
MANIFEST_LIMIT=500
LONG_MANIFEST_LIMIT=1500

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
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || { echo "已有蒸馏任务运行，跳过本轮"; exit 0; }
fi

MANIFEST=$(python3 - "$VAULT" "$STATE_FILE" "$MANIFEST_LIMIT" "$LONG_MANIFEST_LIMIT" "$PROVIDER" "$LONG_CONTEXT_PROVIDERS" <<'PY'
import json, sys
from pathlib import Path
vault=Path(sys.argv[1]); state_path=Path(sys.argv[2])
limit=int(sys.argv[3]); long_limit=int(sys.argv[4])
prov=sys.argv[5]; long_providers=set(sys.argv[6].split(','))
# 长上下文 provider 提高上限
if prov in long_providers:
    limit = long_limit
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
if len(rows) > limit:
    print(f"⚠️ 本轮变更文件 {len(rows)} 个，超过上限 {limit}，截断处理（剩余 {len(rows)-limit} 个将在后续轮次补齐）", file=sys.stderr)
print("\n".join(rows[:limit]))
PY
)
if [ -z "$MANIFEST" ]; then
  echo "没有新增或修改的 Raw Chat Logs，跳过本轮蒸馏"
  exit 0
fi
PROMPT_BASE=$(cat <<EOF
读取并蒸馏本轮新增或修改的 AI Raw Chat Logs，把高价值内容沉淀到 Obsidian vault 的 Lessons + Wiki 层。

vault 根目录: $VAULT
本轮只读取下面列出的文件，不要扫描其他 Raw 文件：
$MANIFEST

先读 CLAUDE.md、Wiki/AGENTS.md、Wiki/Index.md。Raw 原文只读，不修改、不删除、不移动。
过滤寒暄、测试、重复工具输出、失败调试过程，只保留最终结论、已验证配置、决策、踩坑、可复用经验和失败边界。
创建或更新 Wiki/Sources/日期-AI-聊天记录摘要.md；按工具写入对应 Lessons，跨工具内容写 Shared/Lessons；已有主题增量合并去重，不重复建页。
遇到新旧结论冲突或发现旧内容错误/过时时，不直接覆盖旧结论：并列保留新旧说法，各自标注来源、时间、适用范围，并写明旧结论的失效原因（哪条信息变了导致它不再成立）。当前正确结论放在最前，旧结论标注「已失效」放后面。
必要时更新 Wiki/Concepts、Entities、Topics、各 Index、Wiki/Log.md。所有事实标注来源，中文输出，敏感信息脱敏。不要修改 CLAUDE.md 和 Wiki/AGENTS.md。

Obsidian 语法规范（按官方 obsidian-markdown 惯例）：
- 「风险 / 边界」「踩坑」「警告」区块用 > [!warning] callout；「待核实」「待确认」用 > [!question] callout；重要结论用 > [!tip] callout
- 半成品/占位信息用 %%注释%% 包裹（阅读视图隐藏，不删内容）
- 内部链接一律用 [[wikilink]]，外部 URL 用 [text](url)
- 日期一律 YYYY-MM-DD 格式；frontmatter 的 aliases 填实际别名（如英文名、缩写），不要留空数组
- 段落级引用用 ^block-id 锚点（精确引用结论时）

完成后汇报：读取文件、新建/更新页面、关键结论、待核实事项。
EOF
)
# ── 能力指令（按 provider 动态注入）──
VISION_INSTRUCTION="日志中的 ![[assets/...]] 图片引用，请用 vision 读取图片内容并纳入蒸馏（图表、截图中的关键信息要总结成文字）。"
TOOL_INSTRUCTION="允许使用工具（读文件/搜索/运行命令）辅助理解上下文。"
MULTILINGUAL_INSTRUCTION="中文输出优先；模型中文不佳时可用英文思考后转成中文输出。"

build_prompt() {
  local prov="$1"
  local extra=""
  # vision 能力
  if echo "$VISION_PROVIDERS" | tr ',' "\n" | grep -qx "$prov"; then
    extra="${extra}${VISION_INSTRUCTION}
"
  fi
  # tool-use 能力
  if echo "$TOOL_USE_PROVIDERS" | tr ',' "\n" | grep -qx "$prov"; then
    extra="${extra}${TOOL_INSTRUCTION}
"
  fi
  # multilingual 能力
  if echo "$MULTILINGUAL_PROVIDERS" | tr ',' "\n" | grep -qx "$prov"; then
    extra="${extra}${MULTILINGUAL_INSTRUCTION}
"
  fi
  # 在「过滤寒暄」前插入能力指令
  if [ -n "$extra" ]; then
    echo -e "${PROMPT_BASE/过滤寒暄/${extra}过滤寒暄}"
  else
    echo -e "$PROMPT_BASE"
  fi
}

if [ "${1:-}" = "--dry-run" ]; then
  printf 'provider=%s\nmodel=%s\nmanifest_limit=%s\nvision=%s\ntool_use=%s\nmultilingual=%s\nvault=%s\nfiles:\n%s\n' "$PROVIDER" "$MODEL" "$MANIFEST_LIMIT" "$(echo "$VISION_PROVIDERS" | tr ',' '\n' | grep -qx "$PROVIDER" && echo yes || echo no)" "$(echo "$TOOL_USE_PROVIDERS" | tr ',' '\n' | grep -qx "$PROVIDER" && echo yes || echo no)" "$(echo "$MULTILINGUAL_PROVIDERS" | tr ',' '\n' | grep -qx "$PROVIDER" && echo yes || echo no)" "$VAULT" "$MANIFEST"
  exit 0
fi
# fallback 链：主 provider 失败时依次降级，避免额度耗尽导致蒸馏中断
FALLBACK_PROVIDERS=()
FALLBACK_MODELS=()
if [ -n "${FALLBACK_PROVIDERS_CSV:-}" ]; then
  IFS=',' read -ra FALLBACK_PROVIDERS <<< "$FALLBACK_PROVIDERS_CSV"
  if [ -n "${FALLBACK_MODELS_CSV:-}" ]; then
    IFS=',' read -ra FALLBACK_MODELS <<< "$FALLBACK_MODELS_CSV"
  fi
  while [ "${#FALLBACK_MODELS[@]}" -lt "${#FALLBACK_PROVIDERS[@]}" ]; do
    FALLBACK_MODELS+=("")
  done
fi

run_distill() {
  local prov="$1" model="$2"
  local out_file="/tmp/distill_output_$$.log"
  local hbin="${HERMES_BIN:-}"
  if [ -z "$hbin" ]; then
    if command -v hermes >/dev/null 2>&1; then
      hbin="$(command -v hermes)"
    elif [ -x "${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/hermes" ]; then
      hbin="${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/hermes"
    fi
  fi
  if [ -z "$hbin" ]; then
    echo "❌ 找不到 hermes CLI（PATH 中无 hermes，且未设置 HERMES_BIN）" >&2
    return 1
  fi
  local prompt
  prompt=$(build_prompt "$prov")
  "$hbin" chat --provider "$prov" -m "$model" -s ai-chat-unified-distill \
    -t file,terminal --in "$VAULT" --max-turns "${AI_DISTILL_MAX_TURNS:-80}" \
    --accept-hooks -Q -q "$prompt" > "$out_file" 2>&1
  local rc=$?
  local failed=0
  if grep -qiE "^API call failed after|^No API key found|^No usable credentials|^HTTP [45][0-9][0-9]" "$out_file"; then
    failed=1
  fi
  local lines
  lines=$(wc -l < "$out_file" 2>/dev/null || echo 0)
  if [ "$lines" -le 2 ]; then
    failed=1
  fi
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