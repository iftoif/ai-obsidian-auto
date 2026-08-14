#!/bin/bash
# Weekly high-signal ChromaDB rebuild for Obsidian LLM Wiki.
set -euo pipefail

export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
if [ "$(uname -s)" != "Darwin" ]; then
  export OBSIDIAN_VAULT_PATH="${OBSIDIAN_VAULT_PATH:-$HOME/obsidian}"
fi
PYBIN="$HOME/.hermes/obsidian-backup-env/bin/python3"
SCRIPT="$HOME/.hermes/scripts/wiki_chroma_rebuild.py"

OUTPUT=$("$PYBIN" "$SCRIPT" --vault "$OBSIDIAN_VAULT_PATH" --quiet 2>&1)
RC=$?

if [ $RC -ne 0 ]; then
  echo "❌ Wiki Chroma 重建失败 (exit=$RC)"
  echo "$OUTPUT" | tail -20
  exit $RC
fi

echo "$OUTPUT" | tail -5
