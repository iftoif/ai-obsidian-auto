#!/usr/bin/env bash
# Hermes auto-update watchdog — cron-safe version
# 只检查更新 + 空闲时后台异步安装。
# 不在 cron 内同步执行 hermes update（会触发 gateway 重启导致 cron 超时死锁）。
set -uo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
HERMES_REPO="${HERMES_HOME}/hermes-agent"
HERMES_BIN="${HERMES_REPO}/venv/bin/hermes"
IS_MACOS=false
[ "$(uname -s)" = "Darwin" ] && IS_MACOS=true

LOG="${HERMES_HOME}/logs/auto-update.log"
echo "=== auto-update started $(date '+%Y-%m-%d %H:%M:%S') ===" >> "$LOG"

# ── 1. Check for updates ─────────────────────────────────────────────

UPDATE_OUTPUT=$("${HERMES_BIN}" update --check 2>&1) || true

if echo "${UPDATE_OUTPUT}" | grep -qi "up.to.date\|already.*latest\|no update\|not found"; then
    echo "No update available" >> "$LOG"
    exit 0
fi

echo "Update available: $(echo "${UPDATE_OUTPUT}" | head -3)" >> "$LOG"

# ── 2. 检查是否已经在后台安装（避免重复触发）────────────────────────
if pgrep -f "hermes.*update.*--yes" >/dev/null 2>&1; then
    echo "Update already running in background — skip" >> "$LOG"
    exit 0
fi

# ── 3. 异步安装（nohup 脱离 cron，cron 立即返回不超时）──────────────
echo "Launching background update..." >> "$LOG"
nohup bash -c "
    sleep 30
    echo '=== bg update start \$(date) ===' >> '$LOG'
    '$HERMES_BIN' update --yes >> '$LOG' 2>&1
    echo '=== bg update done \$(date) ===' >> '$LOG'
    # 更新后恢复 systemd EnvironmentFile（update 会覆盖 service 文件）
    sleep 5
    [ -f '$HERMES_HOME/scripts/hermes_update_hook.sh' ] && '$HERMES_HOME/scripts/hermes_update_hook.sh' >> '$LOG' 2>&1
    echo '=== post-update hook done \$(date) ===' >> '$LOG'
" >/dev/null 2>&1 &

echo "Background update launched (async, cron returns immediately)" >> "$LOG"
exit 0
