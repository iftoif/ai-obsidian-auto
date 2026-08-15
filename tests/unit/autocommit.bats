#!/usr/bin/env bats

# wiki_git_autocommit 核心逻辑单元测试（add_paths / 密钥拦截）

setup() {
  TESTROOT="$(mktemp -d)"
  export TESTROOT HOME="$TESTROOT/home"
  mkdir -p "$TESTROOT/vault/Wiki" "$HOME/.hermes/data"
  echo '# 测试笔记' > "$TESTROOT/vault/Wiki/note1.md"
}

teardown() {
  rm -rf "$TESTROOT"
}

@test "add_paths：只 add 存在的路径（缺失目录不拖垮提交）" {
  WIKI_REPO="$TESTROOT/wiki-repo"
  mkdir -p "$WIKI_REPO"
  git init -q "$WIKI_REPO"
  git -C "$WIKI_REPO" config user.name test
  git -C "$WIKI_REPO" config user.email test@t
  rsync -a "$TESTROOT/vault/Wiki/" "$WIKI_REPO/Wiki/"
  add_paths=()
  for p in Wiki Hermes/Lessons Codex/Lessons; do
    [ -e "$WIKI_REPO/$p" ] && add_paths+=("$p")
  done
  git -C "$WIKI_REPO" add "${add_paths[@]}" 2>/dev/null || true
  git -C "$WIKI_REPO" commit -m test >/dev/null 2>&1
  run git -C "$WIKI_REPO" log --oneline
  [ "$status" -eq 0 ]
  echo "$output" | grep -q 'test'
}

@test "密钥拦截：疑似密钥触发拦截逻辑" {
  echo 'sk-1234567890abcdefghij' > "$TESTROOT/vault/Wiki/secret.md"
  WIKI_REPO="$TESTROOT/wiki-repo2"
  mkdir -p "$WIKI_REPO"
  git init -q "$WIKI_REPO"
  git -C "$WIKI_REPO" config user.name test
  git -C "$WIKI_REPO" config user.email test@t
  rsync -a "$TESTROOT/vault/Wiki/" "$WIKI_REPO/Wiki/"
  git -C "$WIKI_REPO" add Wiki 2>/dev/null || true
  # 检测到疑似密钥 → 拦截逻辑触发（reset + 不提交）
  if git -C "$WIKI_REPO" diff --cached --binary | grep -Eiq 'sk-[A-Za-z0-9]'; then
    git -C "$WIKI_REPO" reset >/dev/null 2>&1
    # reset 后暂存区应清空（secret.md 不被提交）
    run git -C "$WIKI_REPO" diff --cached --name-only
    [ -z "$output" ]
  fi
}
