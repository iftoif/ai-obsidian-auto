#!/usr/bin/env bash
set -Eeuo pipefail
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
REPO="${WIKI_REPO:-$HOME/obsidian-wiki}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOCK="$HERMES_HOME/data/wiki-git-autocommit.lock"
mkdir -p "$REPO" "$(dirname "$LOCK")"
exec 9>"$LOCK"
# Linux 用 flock 防并发；macOS 无 flock 命令时跳过锁（本脚本目标平台是 Linux 服务器）
if command -v flock >/dev/null 2>&1; then
  flock -n 9 || exit 0
fi

# 仓库自动初始化：全新部署时 $REPO 可能只是空目录（或不存在）
if [ ! -d "$REPO/.git" ]; then
  echo "初始化 Wiki Git 仓库: $REPO" >&2
  git init -q "$REPO"
  # 强制本地分支命名为 main（不依赖 git 全局 init.defaultBranch 配置）
  git -C "$REPO" branch -M main 2>/dev/null || true
  git -C "$REPO" config user.name  "obsidian-auto" 2>/dev/null || true
  git -C "$REPO" config user.email "obsidian-auto@localhost" 2>/dev/null || true
fi
rsync -a --delete --exclude='.git/' "$VAULT/Wiki/" "$REPO/Wiki/"
for d in Hermes/Lessons Codex/Lessons Claude/Lessons Pi/Lessons Shared/Lessons Context Skills; do
  if [ -d "$VAULT/$d" ]; then
    mkdir -p "$REPO/$(dirname "$d")"
    rsync -a --delete "$VAULT/$d/" "$REPO/$d/"
  fi
done
[ -f "$VAULT/CLAUDE.md" ] && cp "$VAULT/CLAUDE.md" "$REPO/CLAUDE.md"
# 只 add 实际存在的路径：git add 多 pathspec 中任一不存在会整体失败（exit 128），
# 错误被吞掉后所有文件都不暂存、脚本静默退出——知识库永不提交
add_paths=()
for p in Wiki Hermes/Lessons Codex/Lessons Claude/Lessons Pi/Lessons Shared/Lessons Context Skills; do
  [ -e "$REPO/$p" ] && add_paths+=("$p")
done
[ -e "$REPO/CLAUDE.md" ] && add_paths+=("CLAUDE.md")
if [ "${#add_paths[@]}" -gt 0 ]; then
  git -C "$REPO" add "${add_paths[@]}" 2>/dev/null || true
fi
if git -C "$REPO" diff --cached --quiet; then exit 0; fi
if git -C "$REPO" diff --cached --binary | grep -Eiq 'sk-[A-Za-z0-9]|tvly-|cookie[=:]|password[=:]|api[_-]?key[=:][^$]|bearer [A-Za-z0-9]|ghp_[A-Za-z0-9]|github_pat_|xox[baprs]-|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}|BEGIN (RSA |OPENSSH |EC )?PRIVATE KEY'; then
  echo 'secret-like content detected; refusing commit' >&2
  git -C "$REPO" reset >/dev/null
  exit 78
fi
git -C "$REPO" commit -m "chore(wiki): sync knowledge layers $(date +%Y-%m-%d)" >/dev/null
# push：无 remote（全新部署纯本地）只 commit 不 push；
#      遇远端有新提交（非 fast-forward）先 pull --rebase 再推；仍失败告警但不阻塞
# push 用 HEAD:main 显式指定目标分支，不依赖本地分支名
if git -C "$REPO" remote | grep -q . 2>/dev/null; then
  if ! git -C "$REPO" push origin HEAD:main 2>/dev/null; then
    git -C "$REPO" pull --rebase origin main 2>/dev/null || true
    git -C "$REPO" push origin HEAD:main 2>/dev/null || echo "⚠️ Wiki Git push 失败（远端可能有冲突）" >&2
  fi
fi
