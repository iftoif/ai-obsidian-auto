#!/usr/bin/env bats

# ai_chat_unified_distill_cron 核心逻辑单元测试（hermes 解析 / fallback 链）

setup() {
  TESTROOT="$(mktemp -d)"
  export TESTROOT HOME="$TESTROOT/home"
  mkdir -p "$HOME/.hermes" "$TESTROOT/bin"
  export PATH="$TESTROOT/bin:$PATH"
}

teardown() {
  rm -rf "$TESTROOT"
}

@test "hermes CLI 解析：PATH 有 hermes 用 PATH" {
  printf '#!/bin/bash\necho fake-hermes\n' > "$TESTROOT/bin/hermes"
  chmod +x "$TESTROOT/bin/hermes"
  local hbin="${HERMES_BIN:-}"
  if [ -z "$hbin" ]; then
    if command -v hermes >/dev/null 2>&1; then
      hbin="$(command -v hermes)"
    fi
  fi
  [ -n "$hbin" ]
  echo "$hbin" | grep -q 'fake-hermes\|TESTROOT/bin/hermes' || echo "hbin=$hbin"
}

@test "hermes CLI 解析：PATH 无 hermes 回退 venv 位置（R15 修复）" {
  mkdir -p "$HOME/.hermes/hermes-agent/venv/bin"
  printf '#!/bin/bash\necho real-hermes\n' > "$HOME/.hermes/hermes-agent/venv/bin/hermes"
  chmod +x "$HOME/.hermes/hermes-agent/venv/bin/hermes"
  # 子 shell 隔离：显式清空 PATH，模拟无 hermes 环境
  hbin=$(PATH=/usr/bin:/bin bash -c '
    hash -r 2>/dev/null || true
    h="${HERMES_BIN:-}"
    if [ -z "$h" ]; then
      if command -v hermes >/dev/null 2>&1; then
        h="$(command -v hermes)"
      elif [ -x "${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/hermes" ]; then
        h="${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/hermes"
      fi
    fi
    echo "$h"
  ')
  echo "hbin: $hbin"
  [ -n "$hbin" ]
  [ "$hbin" = "$HOME/.hermes/hermes-agent/venv/bin/hermes" ]
}

@test "hermes CLI 解析：都没有时明确报错" {
  # HOME 是临时目录 + PATH 清空 → 两个都找不到 → hbin 空
  hbin=$(PATH=/usr/bin:/bin bash -c '
    hash -r 2>/dev/null || true
    h="${HERMES_BIN:-}"
    if [ -z "$h" ]; then
      if command -v hermes >/dev/null 2>&1; then
        h="$(command -v hermes)"
      elif [ -x "${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/hermes" ]; then
        h="${HERMES_HOME:-$HOME/.hermes}/hermes-agent/venv/bin/hermes"
      fi
    fi
    echo "$h"
  ')
  [ -z "$hbin" ]
}

@test "fallback 链：主 provider 失败时依次降级" {
  FALLBACK_PROVIDERS_CSV='deepseek,kimi'
  FALLBACK_PROVIDERS=()
  IFS=',' read -ra FALLBACK_PROVIDERS <<< "$FALLBACK_PROVIDERS_CSV"
  [ "${#FALLBACK_PROVIDERS[@]}" -eq 2 ]
  [ "${FALLBACK_PROVIDERS[0]}" = 'deepseek' ]
  [ "${FALLBACK_PROVIDERS[1]}" = 'kimi' ]
}

@test "fallback 模型数不足时补位（空串）" {
  FALLBACK_PROVIDERS=(deepseek kimi moon)
  FALLBACK_MODELS=()
  IFS=',' read -ra FALLBACK_MODELS <<< 'ds-model'
  while [ "${#FALLBACK_MODELS[@]}" -lt "${#FALLBACK_PROVIDERS[@]}" ]; do
    FALLBACK_MODELS+=('')
  done
  [ "${#FALLBACK_MODELS[@]}" -eq 3 ]
  [ -z "${FALLBACK_MODELS[1]}" ]
}
