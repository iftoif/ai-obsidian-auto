#!/usr/bin/env bash
set -Eeuo pipefail
VAULT="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
REPO="${WIKI_REPO:-$HOME/obsidian-wiki}"
HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
LOCK="$HERMES_HOME/data/wiki-git-autocommit.lock"
mkdir -p "$REPO" "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -n 9 || exit 0
rsync -a --delete --exclude='.git/' "$VAULT/Wiki/" "$REPO/Wiki/"
for d in Hermes/Lessons Codex/Lessons Claude/Lessons Pi/Lessons Shared/Lessons Context Skills; do
  if [ -d "$VAULT/$d" ]; then
    mkdir -p "$REPO/$(dirname "$d")"
    rsync -a --delete "$VAULT/$d/" "$REPO/$d/"
  fi
done
[ -f "$VAULT/CLAUDE.md" ] && cp "$VAULT/CLAUDE.md" "$REPO/CLAUDE.md"
git -C "$REPO" add Wiki Hermes/Lessons Codex/Lessons Claude/Lessons Pi/Lessons Shared/Lessons Context Skills CLAUDE.md 2>/dev/null || true
if git -C "$REPO" diff --cached --quiet; then exit 0; fi
if git -C "$REPO" diff --cached --binary | grep -Eiq 'sk-[A-Za-z0-9]|tvly-|cookie[=:]|password[=:]|api[_-]?key[=:][^$]|bearer [A-Za-z0-9]'; then
  echo 'secret-like content detected; refusing commit' >&2
  git -C "$REPO" reset >/dev/null
  exit 78
fi
git -C "$REPO" commit -m "chore(wiki): sync knowledge layers $(date +%Y-%m-%d)" >/dev/null
git -C "$REPO" push origin main
